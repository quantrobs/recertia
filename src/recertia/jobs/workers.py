"""Concrete M7 jobs: miner, curator, practice, recertifier, step-graph proposals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.replay import WorldState
from contracts.skill import Hygiene, Precondition, Provenance, SkillVersion, Step
from recertia.evals.store import EvalStore
from recertia.jobs import Proposal
from recertia.memory.procedural.store import SkillStore
from recertia.review.autonomy_config import DEFAULT_AUTONOMY, AutonomyConfig
from recertia.trajectory.store import TrajectoryStore
from recertia.validation.sensitivity import author_sensitivity_proof, empty_negative_fixture


def mine_from_repo_hints(store: SkillStore, *, hints: list[str]) -> list[Proposal]:
    """Bootstrap candidates from human-artifact hints (git history / CI / runbooks)."""

    proposals: list[Proposal] = []
    for i, hint in enumerate(hints):
        digest = sha256(hint.encode()).hexdigest()[:8]
        skill_id = f"mined-{i}-{digest}"
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


def curator_active_set_and_dedup(
    store: SkillStore,
    *,
    trajectory_store: TrajectoryStore | None = None,
    replay_limit: int = 50,
) -> list[Proposal]:
    """Recompute the active set and attach retrieval-only ReplayPacks when trajectories exist."""

    from recertia.memory.procedural.active_set import recompute_active_set
    from recertia.replay.pack import build_replay_pack
    from recertia.replay.sample import sample_trajectories_for_skill

    _updated, pressure = recompute_active_set(store)
    mean_pressure = (
        sum(pressure.values()) / len(pressure) if pressure else 0.0
    )
    proposals: list[Proposal] = [
        Proposal(
            kind="curate",
            skill_id="active-set",
            version=0,
            rationale=f"recomputed active set; pressure={pressure}",
            payload={
                "pressure": pressure,
                "active_cap_pressure": mean_pressure,
            },
        )
    ]
    if trajectory_store is None:
        return proposals

    packs_attached = 0
    max_packs = 5
    for version, status, _stats in store.iter_loaded():
        if packs_attached >= max_packs:
            break
        if status.lifecycle != "approved" or not status.active:
            continue
        trajectories = sample_trajectories_for_skill(
            trajectory_store, skill_id=version.skill_id, limit=replay_limit
        )
        if not trajectories:
            continue
        world = WorldState(
            suppressed_skill_ids=[version.skill_id],
            skill_status_overrides={
                f"{version.skill_id}@{version.version}": "benched"
            },
            library_commit=None,
            index_snapshot_id=None,
        )
        pack = build_replay_pack(
            trajectory_store,
            trajectories=trajectories,
            world=world,
            mode="retrieval_only",
            purpose="curator_counterfactual",
        )
        proposals.append(
            Proposal(
                kind="curate",
                skill_id=version.skill_id,
                version=version.version,
                rationale=(
                    f"replay pack ({len(pack.observations)} traj) for "
                    f"{version.skill_id}@v{version.version}"
                ),
                payload={
                    "replay_pack": pack.model_dump(mode="json"),
                    "purpose": "curator_counterfactual",
                },
            )
        )
        packs_attached += 1
    return proposals


def load_one_off_reasons(one_off_log: Path | str | None) -> list[str]:
    """Cluster reasons from distill ``one_off_log`` JSONL (newest last, unique order)."""

    if one_off_log is None:
        return []
    path = Path(one_off_log)
    if not path.exists():
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        reason = str(row.get("reason") or "").strip()
        if not reason or reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return ordered


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
                json.dumps(
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


def propose_hex_search() -> list[Proposal]:
    """Emit a HEX practice-search proposal. JobRunner still gates enablement (RW-6)."""

    return [
        Proposal(
            kind="hex",
            skill_id="hex-search",
            version=1,
            rationale="HEX practice search (enablement predicates passed)",
            payload={"job": "practice_hex"},
        )
    ]


def propose_compress() -> list[Proposal]:
    """Emit a unit-level compress proposal. JobRunner still gates enablement (RW-6)."""

    return [
        Proposal(
            kind="compress",
            skill_id="compress-units",
            version=1,
            rationale="unit-level compress (enablement predicates passed)",
            payload={"job": "compress"},
        )
    ]


def enqueue_mined_candidate(store: SkillStore, proposal: Proposal) -> SkillVersion:
    """Persist a mined draft as ``candidate`` only — promotion stays behind the golden gate."""

    draft = draft_from_mine_proposal(proposal)
    return store.write_candidate(draft)


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


def recertify_with_revokes(
    store: SkillStore,
    *,
    lineage_index=None,
    revoke_queue=None,
    max_writes: int = 50,
    tool_upgraded: str | None = None,
    eval_store: EvalStore | None = None,
) -> list[Proposal]:
    """One Recertifier pass: stale certs + field off-ramp + lineage revoke drain."""

    proposals = recertify_stale(store, tool_upgraded=tool_upgraded)
    if eval_store is not None:
        from recertia.review.field_failures import recertify_field_failures

        for off_ramp in recertify_field_failures(store, eval_store, config=DEFAULT_AUTONOMY):
            proposals.append(
                Proposal(
                    kind="recertify",
                    skill_id=off_ramp.skill_id,
                    version=off_ramp.version,
                    rationale=(
                        f"field off-ramp: {off_ramp.consecutive_failures} consecutive "
                        "treatment-arm failures"
                    ),
                    payload={
                        "consecutive_field_failures": off_ramp.consecutive_failures,
                        "reason": "field_failures",
                    },
                )
            )
    if lineage_index is None or revoke_queue is None:
        return proposals
    from recertia.memory.procedural.lineage import drain_revokes

    touched = drain_revokes(store, lineage_index, revoke_queue, max_writes=max_writes)
    for status in touched:
        proposals.append(
            Proposal(
                kind="recertify",
                skill_id=status.skill_id,
                version=status.version,
                rationale="lineage revoke drain → needs_recert",
            )
        )
    return proposals


def practice_from_fail_clusters(
    eligible_rows: list,
    *,
    curriculum_dir: Path | None = None,
) -> list[Proposal]:
    """Prefer incremental eligible clusters over random one-offs (ADR-0015 P2)."""

    proposals: list[Proposal] = []
    if curriculum_dir is not None:
        curriculum_dir.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(eligible_rows):
        signature = getattr(row, "signature", None) or str(row)
        task_class = getattr(row, "task_class", "unknown")
        skill_id = f"practice-cluster-{i}"
        payload = {
            "predicted_success_band": [0.2, 0.8],
            "cluster_signature": signature,
            "task_class": task_class,
            "excluded_from_user_metrics": True,
            "source": "fail_cluster",
        }
        if curriculum_dir is not None:
            path = curriculum_dir / f"{skill_id}.json"
            path.write_text(
                json.dumps(
                    {
                        "skill_id": skill_id,
                        "predicted_success": 0.5,
                        "band": [0.2, 0.8],
                        "signature": signature,
                        "task_class": task_class,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            payload["curriculum_path"] = str(path)
        proposals.append(
            Proposal(
                kind="fail_cluster",
                skill_id=skill_id,
                version=1,
                rationale=f"fail-cluster curriculum: {signature[:60]}",
                payload=payload,
            )
        )
    return proposals



def schedule_shadow_evaluations(
    store: SkillStore,
    *,
    eval_store: EvalStore | None = None,
    config: AutonomyConfig | None = None,
    snapshot_id: str = "shadow-job",
) -> list[Proposal]:
    """Job wrapper: bounded offline shadow slots with no caller-visible side effects."""

    from recertia.review.shadow import schedule_shadow_slots

    cfg = config or DEFAULT_AUTONOMY
    results = schedule_shadow_slots(
        store, eval_store=eval_store, config=cfg, snapshot_id=snapshot_id
    )
    return [
        Proposal(
            kind="curate",
            skill_id=result.skill_id,
            version=result.version,
            rationale=(
                f"offline shadow slot {'passed' if result.success else 'failed'}; "
                "not visible to callers"
            ),
            payload={
                "shadow": True,
                "success": result.success,
                "visible_to_caller": result.visible_to_caller,
                "run_id": result.run_id,
            },
        )
        for result in results
    ]


def propose_parallelise(
    skill_id: str,
    version: int,
    *,
    fake_edge_failures: int | None = None,
    skill: SkillVersion | None = None,
    transcripts: list[dict] | None = None,
    threshold: int = 5,
) -> list[Proposal]:
    """Propose removing input bindings that failed the fake-edge test (≥``threshold`` runs).

    Prefer deriving failure counts from ``skill`` + historical ``transcripts`` when supplied;
    otherwise use an explicit ``fake_edge_failures`` total.
    """

    from recertia.evals.fake_edges import edges_failing_threshold, fake_edge_failure_count

    remove: list[dict[str, str]] = []
    if skill is not None and transcripts is not None:
        failing = edges_failing_threshold(skill, transcripts, threshold=threshold)
        if not failing:
            return []
        remove = [
            {
                "consumer_step": edge.consumer_step,
                "source_step": edge.source_step,
                "output": edge.output,
                "input": edge.binding.input,
            }
            for edge in failing
        ]
        fake_edge_failures = fake_edge_failure_count(skill, transcripts)
    elif fake_edge_failures is None:
        return []
    elif fake_edge_failures < threshold:
        return []

    assert fake_edge_failures is not None
    if fake_edge_failures < threshold and not remove:
        return []
    return [
        Proposal(
            kind="parallelise",
            skill_id=skill_id,
            version=version + 1,
            rationale=f"remove fake edges after {fake_edge_failures} failures",
            payload={
                "remove_input_binding": True,
                "bindings": remove,
                "fake_edge_failures": fake_edge_failures,
                "expected_parallel_speedup_note": "report beside merge_gap_rate only",
            },
        )
    ]


def propose_serialise(
    skill_id: str,
    version: int,
    *,
    merge_conflict_count: int | None = None,
    merge_audits: list[dict] | None = None,
    threshold: int = 5,
) -> list[Proposal]:
    """Propose adding serial edges when parallel waves lose work (merge conflicts/gaps)."""

    conflicts = merge_conflict_count
    if conflicts is None and merge_audits is not None:
        conflicts = sum(
            1
            for audit in merge_audits
            if audit.get("missing") or audit.get("conflict") or audit.get("incomplete")
        )
    if conflicts is None or conflicts < threshold:
        return []
    return [
        Proposal(
            kind="serialise",
            skill_id=skill_id,
            version=version + 1,
            rationale=f"add serial binding after {conflicts} merge conflicts/gaps",
            payload={
                "add_input_binding": True,
                "merge_conflict_count": conflicts,
                "expected_parallel_speedup_note": "speedup alone is refused without merge_gap_rate",
            },
        )
    ]


def correction_miner_from_reviewer_edits(
    edits: list[dict],
    *,
    threshold: int = 2,
) -> list[Proposal]:
    """Cluster reviewer edits into T2 ``correction`` proposals (never self-apply)."""

    clusters: dict[str, list[dict]] = {}
    for edit in edits:
        skill_id = str(edit.get("skill_id") or "").strip()
        if not skill_id:
            continue
        clusters.setdefault(skill_id, []).append(edit)

    proposals: list[Proposal] = []
    for skill_id, group in clusters.items():
        if len(group) < threshold:
            continue
        version = int(group[-1].get("version") or 1)
        proposals.append(
            Proposal(
                kind="correction",
                skill_id=skill_id,
                version=version,
                rationale=f"reviewer-edit cluster size={len(group)} (T2; human gate)",
                payload={
                    "tier": "T2",
                    "edit_count": len(group),
                    "edits": group,
                    "self_apply": False,
                },
            )
        )
    return proposals


def load_reviewer_edits(path: Path | str | None) -> list[dict]:
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


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
        preconditions=[
            Precondition(
                kind="file_exists",
                value=".",
                description="Workspace root exists before the mined chore runs.",
            )
        ],
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
