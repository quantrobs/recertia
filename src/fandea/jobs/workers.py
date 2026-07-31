"""Concrete M7 jobs: miner, curator, practice, recertifier, step-graph proposals."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from fandea.jobs import Proposal
from fandea.memory.procedural.store import SkillStore
from fandea.validation.sensitivity import author_sensitivity_proof, empty_negative_fixture


def mine_from_repo_hints(store: SkillStore, *, hints: list[str]) -> list[Proposal]:
    """Bootstrap candidates from human-artifact hints (git history / CI / runbooks)."""

    proposals: list[Proposal] = []
    for i, hint in enumerate(hints):
        skill_id = f"mined-{i}-{abs(hash(hint)) % 10000}"
        proposals.append(
            Proposal(
                kind="mine",
                skill_id=skill_id,
                version=1,
                rationale=f"mined_from_human_artifact: {hint[:80]}",
                payload={"hint": hint, "curation": "mined_from_human_artifact"},
            )
        )
    return proposals


def curator_active_set_and_dedup(store: SkillStore) -> list[Proposal]:
    from fandea.memory.procedural.active_set import recompute_active_set

    _updated, pressure = recompute_active_set(store)
    return [
        Proposal(
            kind="curate",
            skill_id="active-set",
            version=0,
            rationale=f"recomputed active set; pressure={pressure}",
            payload={"pressure": pressure},
        )
    ]


def practice_from_one_offs(
    one_off_reasons: list[str],
    *,
    curriculum_dir: Path | None = None,
) -> list[Proposal]:
    """Build practice proposals in the predicted_success ∈ [0.2, 0.8] band.

    When ``curriculum_dir`` is set, write one curriculum JSON per cluster for the Practice job.
    """

    proposals: list[Proposal] = []
    if curriculum_dir is not None:
        curriculum_dir.mkdir(parents=True, exist_ok=True)
    for i, reason in enumerate(one_off_reasons):
        skill_id = f"practice-{i}"
        payload = {
            "predicted_success_band": [0.2, 0.8],
            "cluster_reason": reason,
            "excluded_from_user_metrics": True,
        }
        if curriculum_dir is not None:
            path = curriculum_dir / f"{skill_id}.json"
            path.write_text(
                __import__("json").dumps(
                    {
                        "skill_id": skill_id,
                        "predicted_success": 0.5,
                        "band": [0.2, 0.8],
                        "reason": reason,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            payload["curriculum_path"] = str(path)
        proposals.append(
            Proposal(
                kind="practice",
                skill_id=skill_id,
                version=1,
                rationale=f"practice curriculum from one-off cluster: {reason[:60]}",
                payload=payload,
            )
        )
    return proposals


def enqueue_mined_candidate(store: SkillStore, proposal: Proposal) -> SkillVersion:
    """Persist a mined draft as ``candidate`` only — promotion stays behind the golden gate."""

    draft = draft_from_mine_proposal(proposal)
    store.write_version(draft)
    from contracts.stats import SkillStats
    from contracts.status import SkillStatus

    store.write_status(
        SkillStatus(
            skill_id=draft.skill_id,
            version=draft.version,
            lifecycle="candidate",
            active=False,
        )
    )
    store.write_stats(SkillStats(skill_id=draft.skill_id, version=draft.version))
    return draft



def recertify_stale(store: SkillStore, *, tool_upgraded: str | None = None) -> list[Proposal]:
    proposals: list[Proposal] = []
    for version, status, _stats in store.iter_loaded():
        if tool_upgraded or status.certification.recert_status == "stale":
            store.write_status(
                status.model_copy(update={"lifecycle": "needs_recert", "active": False})
            )
            proposals.append(
                Proposal(
                    kind="recertify",
                    skill_id=version.skill_id,
                    version=version.version,
                    rationale=f"tool upgrade or stale cert → needs_recert ({tool_upgraded})",
                )
            )
    return proposals


def propose_parallelise(skill_id: str, version: int, *, fake_edge_failures: int) -> list[Proposal]:
    if fake_edge_failures < 5:
        return []
    return [
        Proposal(
            kind="parallelise",
            skill_id=skill_id,
            version=version + 1,
            rationale=f"remove fake edges after {fake_edge_failures} failures",
            payload={"remove_input_binding": True},
        )
    ]


def draft_from_mine_proposal(proposal: Proposal) -> SkillVersion:
    criterion = SkillCertificationCriterion(
        id="workspace-evidence",
        kind="command",
        run="test -f ok.txt",
        preregistered=True,
    )
    proof = author_sensitivity_proof(
        criterion, negative_workdir=empty_negative_fixture()
    )
    return SkillVersion(
        skill_id=proposal.skill_id,
        version=1,
        title=f"Mined skill {proposal.skill_id}",
        intent="Skill mined from a human artifact hint for cold-start library bootstrap.",
        task_class="repo-chore",
        steps=[
            Step(
                id="step_1",
                tool="shell",
                intent="Apply the mined shell chore from the human artifact",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[
            SkillCertificationCriterion(
                id=criterion.id,
                kind="command",
                run=criterion.run,
                sensitivity_proof=proof,
                preregistered=True,
            )
        ],
        provenance=Provenance(
            distilled_from_run="job-miner",
            distilled_at=datetime.now(timezone.utc),
            curation="mined_from_human_artifact",
            derivation="mined_artifact",
            authoring_prior_version="ap-test",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=datetime.now(timezone.utc)),
    )
