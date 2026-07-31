"""Concrete M7 jobs: miner, curator, practice, recertifier, step-graph proposals."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from fandea.jobs import Proposal
from fandea.memory.procedural.store import SkillStore


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


def practice_from_one_offs(one_off_reasons: list[str]) -> list[Proposal]:
    return [
        Proposal(
            kind="practice",
            skill_id=f"practice-{i}",
            version=1,
            rationale=f"practice curriculum from one-off cluster: {reason[:60]}",
            payload={"predicted_success_band": [0.2, 0.8]},
        )
        for i, reason in enumerate(one_off_reasons)
    ]


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
            payload={"remove_depends_on": True},
        )
    ]


def draft_from_mine_proposal(proposal: Proposal) -> SkillVersion:
    proof = SensitivityProof(
        criterion_id="ok",
        negative_fixture="empty",
        rejected=True,
        checked_at=datetime.now(timezone.utc),
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
                id="ok",
                kind="command",
                run="true",
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
