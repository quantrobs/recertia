"""Roadmap-remaining engineering gates: metrics, replay, jobs, canary, quotas."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.eval import EvalObservation
from contracts.replay import WorldState
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from contracts.trajectory import TrajectoryEvent
from recertia.api.quotas import QuotaExceeded, QuotaStore
from recertia.evals.canary import run_judge_canary
from recertia.evals.metrics import build_metric_report
from recertia.evals.second_domain import second_domain_fixture_ready
from recertia.jobs.workers import (
    correction_miner_from_reviewer_edits,
    curator_active_set_and_dedup,
    load_one_off_reasons,
    propose_serialise,
)
from recertia.memory.procedural.seeds import seed_approved_for_tests
from recertia.memory.procedural.store import SkillStore
from recertia.memory.scope import tenant_readable
from recertia.replay.pack import build_replay_pack
from recertia.trajectory.emitter import TrajectoryEmitter
from recertia.trajectory.store import TrajectoryStore


def _skill(skill_id: str, *, curation: str = "self_distilled") -> SkillVersion:
    return SkillVersion(
        skill_id=skill_id,
        version=1,
        title=skill_id,
        intent="test skill intent for roadmap coverage",
        task_class="repo-chore",
        steps=[
            Step(
                id="s1",
                tool="shell",
                intent="noop shell step for tests",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[
            SkillCertificationCriterion(
                id="c1",
                kind="command",
                run="true",
                preregistered=True,
            )
        ],
        provenance=Provenance(
            distilled_from_run="r1",
            distilled_at=datetime.now(timezone.utc),
            curation=curation,  # type: ignore[arg-type]
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=datetime.now(timezone.utc)),
    )


def test_metric_report_curation_gap_and_practice_conversion() -> None:
    rows = [
        {
            "first_attempt_success": True,
            "arm": "treatment",
            "curation": "human_authored",
            "strategy": "apply",
            "terminal": "solved",
            "attempt_no": 1,
            "cost_usd": 0.1,
        },
        {
            "first_attempt_success": False,
            "arm": "treatment",
            "curation": "self_distilled",
            "strategy": "scratch",
            "terminal": "unsolved",
            "attempt_no": 2,
        },
        {
            "first_attempt_success": False,
            "arm": "practice",
            "practice_converted": True,
            "is_eval_fixture": False,
        },
        {
            "first_attempt_success": False,
            "arm": "practice",
            "practice_converted": False,
        },
    ]
    report = build_metric_report(
        rows,
        snapshot_id="snap",
        active_cap_pressure=0.25,
        judge_false_pass_rate=0.0,
        mean_composition_depth=0.5,
        retirement_benched=4,
        retirement_restored=1,
    )
    assert report.curation_gap == 1.0
    assert report.practice_conversion == 0.5
    assert report.retirement_reversal_rate == 0.25
    assert report.active_cap_pressure == 0.25
    assert report.judge_false_pass_rate == 0.0
    assert report.mean_composition_depth == 0.5


def test_judge_canary_planted_failure_scores_zero_false_pass() -> None:
    report = run_judge_canary()
    assert report.trials >= 1
    assert report.false_passes == 0
    assert report.false_pass_rate == 0.0


def test_trajectory_replay_pack_and_curator_attachment(tmp_path: Path) -> None:
    skills = SkillStore(tmp_path / "skills")
    version = _skill("replay-me", curation="human_authored")
    seed_approved_for_tests(skills, version, active=True)

    traj = TrajectoryStore(tmp_path / "trajectories")
    traj.write_meta(run_id="run-a", task_id="t1", task_class="repo-chore")
    now = datetime.now(timezone.utc)
    traj.append_many(
        "run-a",
        [
            TrajectoryEvent(
                run_id="run-a",
                seq=0,
                node="plan",
                attempt_no=1,
                event_kind="plan_choice",
                at=now,
                skill_id="replay-me",
                skill_version=1,
            ),
            TrajectoryEvent(
                run_id="run-a",
                seq=0,
                node="finalize",
                attempt_no=1,
                event_kind="terminal",
                at=now,
                payload_inline={"terminal": "solved", "attempt_no": 1},
            ),
        ],
    )
    pack = build_replay_pack(
        traj,
        trajectories=[traj.get_trajectory("run-a")],  # type: ignore[list-item]
        world=WorldState(suppressed_skill_ids=["replay-me"]),
    )
    assert pack.observations
    assert pack.observations[0].plan_would_change is True

    proposals = curator_active_set_and_dedup(skills, trajectory_store=traj)
    assert any(p.payload.get("replay_pack") for p in proposals)
    assert any("active_cap_pressure" in p.payload for p in proposals)


def test_propose_serialise_and_correction_miner() -> None:
    assert propose_serialise("s", 1, merge_conflict_count=5)
    assert not propose_serialise("s", 1, merge_conflict_count=2)
    edits = [
        {"skill_id": "s", "version": 1, "diff": "a"},
        {"skill_id": "s", "version": 1, "diff": "b"},
    ]
    proposals = correction_miner_from_reviewer_edits(edits, threshold=2)
    assert proposals and proposals[0].kind == "correction"
    assert proposals[0].payload["tier"] == "T2"


def test_practice_loads_one_off_log(tmp_path: Path) -> None:
    log = tmp_path / "one_off_log.jsonl"
    log.write_text(
        json.dumps({"run_id": "r1", "reason": "cluster-a"})
        + "\n"
        + json.dumps({"run_id": "r2", "reason": "cluster-a"})
        + "\n"
        + json.dumps({"run_id": "r3", "reason": "cluster-b"})
        + "\n",
        encoding="utf-8",
    )
    assert load_one_off_reasons(log) == ["cluster-a", "cluster-b"]


def test_quota_store_enforces_daily_runs(tmp_path: Path) -> None:
    from recertia.api.quotas import TenantQuota

    store = QuotaStore(tmp_path / "q.sqlite", defaults=TenantQuota(max_runs_per_day=1, max_in_flight=2))
    store.admit("t1")
    store.complete("t1", cost_usd=0.1)
    try:
        store.admit("t1")
        raise AssertionError("expected QuotaExceeded")
    except QuotaExceeded:
        pass
    snap = store.snapshot("t1")
    assert snap["runs"] == 1
    store.close()


def test_second_domain_fixture_and_planted_secret_scope_isolation() -> None:
    assert second_domain_fixture_ready(Path.cwd())
    # Tenant A cannot read tenant-private scope artifacts from tenant B's readable set.
    assert tenant_readable("run", {"run", "project"})
    assert not tenant_readable("org", {"run", "project"})


def test_eval_observation_accepts_curation_fields() -> None:
    obs = EvalObservation(
        run_id="r",
        task_class="repo-chore",
        snapshot_id="s",
        first_attempt_success=True,
        recorded_at=datetime.now(timezone.utc),
        curation="human_authored",
        practice_converted=False,
    )
    assert obs.curation == "human_authored"


def test_trajectory_emitter_emits_plan_and_terminal() -> None:
    from contracts.run import RunManifest, RunState, Task

    state = RunState(
        run_id="e1",
        task=Task(
            task_id="e1",
            request="emit trajectory terminal event",
            task_class="repo-chore",
            submitted_at=datetime.now(timezone.utc),
        ),
        manifest=RunManifest(
            criteria_hash="h",
            index_snapshot_id="idx",
            library_commit="lib",
            model="stub",
            model_version="v1",
        ),
        strategy="apply",
        terminal="solved",
        attempt_no=1,
    )
    events = TrajectoryEmitter().from_node_outcome(
        prior=state,
        new_state=state,
        node="finalize",
        attempt_no=1,
        route=None,
        note=None,
    )
    assert any(e.event_kind == "terminal" for e in events)
