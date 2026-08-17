"""M5 done-when suite: shadow autonomy, quarantine, retirement, active-set cap."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import (
    CriterionResult,
    SkillCertificationCriterion,
    TaskCriterion,
    mint_rejecting_proof,
)
from contracts.run import RunManifest, RunState, SkillCandidateRef, Task
from contracts.skill import Hygiene, Provenance, SkillUse, SkillVersion, Step
from contracts.stats import Contribution, PredictiveTrust, SkillStats
from contracts.status import SkillStatus
from recertia.evals.store import EvalStore
from recertia.ledger import HashChainLedger
from recertia.memory.procedural.active_set import recompute_active_set, select_shadow_slots
from recertia.memory.procedural.seeds import seed_approved_for_tests
from recertia.memory.procedural.store import SkillStore
from recertia.review.autonomy_config import DEFAULT_AUTONOMY, HARSH_AUTONOMY
from recertia.review.lifecycle import (
    LifecycleError,
    maybe_advance_shadow_to_candidate,
    maybe_bench_on_contribution,
    quarantine_on_failures,
    restore_benched,
)
from recertia.review.shadow import record_shadow_outcome


def _skill(
    skill_id: str,
    *,
    task_class: str = "repo-chore",
    uses: list[SkillUse] | None = None,
) -> SkillVersion:
    base = SkillCertificationCriterion(
        id="ok",
        kind="command",
        run="true",
        preregistered=True,
    )
    return SkillVersion(
        skill_id=skill_id,
        version=1,
        title=f"Title for {skill_id} skill",
        intent=f"Intent text long enough for {skill_id} skill version contract.",
        task_class=task_class,
        uses=uses or [],
        steps=[
            Step(
                id="step_1",
                tool="shell",
                intent="Run a trivial shell step for the autonomy fixture",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[
            base.model_copy(
                update={"sensitivity_proof": mint_rejecting_proof(base, fingerprint="m5-ok")}
            )
        ],
        provenance=Provenance(
            distilled_from_run="m5",
            distilled_at=datetime.now(timezone.utc),
            curation="human_authored",
            authoring_prior_version="ap-test",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=datetime.now(timezone.utc)),
    )


def _seed(store: SkillStore, version: SkillVersion, *, lifecycle: str = "shadow") -> None:
    if lifecycle == "approved":
        seed_approved_for_tests(store, version, active=False)
        return
    store.write_version(version)
    store.write_status(
        SkillStatus(skill_id=version.skill_id, version=1, lifecycle=lifecycle, active=False)  # type: ignore[arg-type]
    )
    store.write_stats(SkillStats(skill_id=version.skill_id, version=1))


def _record_evidence(
    eval_store: EvalStore,
    *,
    skill_id: str,
    prefix: str,
    shadow: tuple[int, int],
    suppression: tuple[int, int],
) -> None:
    criterion = TaskCriterion(id="non-judge", kind="command", run="true", source="caller")

    def append(run_id: str, arm: str, success: bool, chosen: bool) -> None:
        eval_store.append_run(
            RunState(
                run_id=run_id,
                task=Task(
                    task_id=run_id,
                    request="evidence fixture",
                    task_class="repo-chore",
                    submitted_at=datetime.now(timezone.utc),
                ),
                manifest=RunManifest(index_snapshot_id="evidence-snapshot", criteria_hash="locked"),
                arm=arm,  # type: ignore[arg-type]
                criteria=[criterion],
                criteria_locked_at=datetime.now(timezone.utc),
                chosen=(
                    SkillCandidateRef(skill_id=skill_id, version=1, score=1.0)
                    if chosen
                    else None
                ),
                suppressed_skill=(
                    SkillCandidateRef(skill_id=skill_id, version=1, score=1.0)
                    if arm == "control"
                    else None
                ),
                attempt_no=1,
                results=[CriterionResult(criterion_id=criterion.id, kind="command", passed=success)],
                terminal="solved" if success else "unsolved",
            )
        )

    successes, trials = shadow
    for index in range(trials):
        append(f"{prefix}-s-{index}", "shadow", index < successes, True)
    successes, trials = suppression
    for index in range(trials):
        append(f"{prefix}-c-{index}", "control", index < successes, False)


def test_shadow_auto_promote_requires_lift(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    eval_store = EvalStore(tmp_path / "evals.sqlite")
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    _seed(store, _skill("shadow-winner"))
    for _ in range(10):
        record_shadow_outcome(store, "shadow-winner", 1, success=True)
    _record_evidence(
        eval_store,
        skill_id="shadow-winner",
        prefix="winner",
        shadow=(10, 10),
        suppression=(5, 10),
    )
    approved = maybe_advance_shadow_to_candidate(
        store, "shadow-winner", 1, eval_store=eval_store, ledger=ledger
    )
    assert approved.lifecycle == "candidate"
    assert approved.active is False

    # High trust, zero lift → refuse
    _seed(store, _skill("zero-lift"))
    for _ in range(10):
        record_shadow_outcome(store, "zero-lift", 1, success=True)
    zero_eval_store = EvalStore(tmp_path / "zero-evals.sqlite")
    _record_evidence(
        zero_eval_store,
        skill_id="zero-lift",
        prefix="zero",
        shadow=(10, 10),
        suppression=(10, 10),
    )
    with pytest.raises(LifecycleError, match="refusing auto-promote"):
        maybe_advance_shadow_to_candidate(store, "zero-lift", 1, eval_store=zero_eval_store)
    eval_store.close()
    zero_eval_store.close()


def test_quarantine_on_injected_regression(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    _seed(store, _skill("regressed"), lifecycle="approved")
    status = quarantine_on_failures(
        store, "regressed", 1, consecutive_failures=3, ledger=ledger
    )
    assert status.lifecycle == "quarantined"
    assert status.active is False


def test_bench_respects_evidence_floor_and_is_restorable(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    eval_store = EvalStore(tmp_path / "evals.sqlite")
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    _seed(store, _skill("neg-contrib"), lifecycle="approved")
    # Below floor
    store.write_stats(
        SkillStats(
            skill_id="neg-contrib",
            version=1,
            predictive_trust=PredictiveTrust(applications=5, successes=0),
            contribution=Contribution(applications=5, successes=0),
        )
    )
    with pytest.raises(LifecycleError, match="evidence floor"):
        maybe_bench_on_contribution(
            store, "neg-contrib", 1, eval_store=eval_store, config=DEFAULT_AUTONOMY
        )

    # Past floor with sustained negative contribution
    _record_evidence(
        eval_store,
        skill_id="neg-contrib",
        prefix="negative",
        shadow=(5, 40),
        suppression=(32, 40),
    )
    benched = maybe_bench_on_contribution(
        store, "neg-contrib", 1, eval_store=eval_store, ledger=ledger
    )
    assert benched.lifecycle == "benched"
    restored = restore_benched(store, "neg-contrib", 1, ledger=ledger)
    assert restored.lifecycle == "candidate"
    assert restored.retirement.restored_at is not None
    eval_store.close()


def test_harsh_config_over_prunes_vs_defaults(tmp_path: Path) -> None:
    """Synthetic harsh config (floor 20, threshold 0) benches more than defaults."""

    def setup(root: Path, config_name: str) -> int:
        store = SkillStore(root / config_name)
        eval_store = EvalStore(root / f"{config_name}.sqlite")
        benched = 0
        for i in range(5):
            sid = f"skill-{config_name}-{i}"
            _seed(store, _skill(sid), lifecycle="approved")
            # 25 apps (past HARSH floor 20, below default 30). Strong enough
            # that interval_high < 0 so HARSH (τ=0) benches; DEFAULT never
            # reaches the floor (ADR-0016).
            _record_evidence(
                eval_store,
                skill_id=sid,
                prefix=sid,
                shadow=(4, 25),
                suppression=(20, 25),
            )
            cfg = HARSH_AUTONOMY if config_name == "harsh" else DEFAULT_AUTONOMY
            try:
                maybe_bench_on_contribution(
                    store, sid, 1, eval_store=eval_store, config=cfg
                )
                benched += 1
            except LifecycleError:
                pass
        eval_store.close()
        return benched

    harsh = setup(tmp_path, "harsh")
    loose = setup(tmp_path, "loose")
    assert harsh > loose


def test_active_cap_pressure(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    for i in range(6):
        sid = f"cap-{i}"
        seed_approved_for_tests(store, _skill(sid), active=True)
        store.write_stats(
            SkillStats(
                skill_id=sid,
                version=1,
                predictive_trust=PredictiveTrust(applications=10 + i, successes=5 + i),
                contribution=Contribution(
                    applications=10 + i,
                    successes=5 + i,
                    suppressed_applications=10,
                    suppressed_successes=3,
                ),
            )
        )
    _updated, pressure = recompute_active_set(
        store, config=HARSH_AUTONOMY  # cap=3
    )
    actives = sum(
        1
        for _v, s, _st in store.iter_loaded()
        if s.lifecycle == "approved" and s.active
    )
    assert actives <= HARSH_AUTONOMY.active_cap_per_task_class + HARSH_AUTONOMY.incumbent_grace_applications
    assert pressure["repo-chore"] > 0


def test_shadow_slots_are_bounded_and_never_expand_active_cap(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    for i in range(5):
        _seed(store, _skill(f"benched-{i}"), lifecycle="benched")
    for i in range(5):
        _seed(store, _skill(f"approved-{i}"), lifecycle="approved")
    slots = select_shadow_slots(store, config=HARSH_AUTONOMY)
    assert len(slots) == HARSH_AUTONOMY.shadow_slots_per_task_class
    assert {slot.reason for slot in slots} <= {"benched", "newly_approved"}
    assert all(not status.active for _version, status, _stats in store.iter_loaded())


def test_shadow_scheduling_job_persists_offline_outcomes(tmp_path: Path) -> None:
    from recertia.jobs.workers import schedule_shadow_evaluations
    from recertia.review.shadow import schedule_shadow_slots

    store = SkillStore(tmp_path / "skills")
    eval_store = EvalStore(tmp_path / "shadow-evals.sqlite")
    for i in range(3):
        _seed(store, _skill(f"bench-shadow-{i}"), lifecycle="benched")
    for i in range(2):
        sid = f"approved-inactive-{i}"
        _seed(store, _skill(sid), lifecycle="approved")
        store.write_status(
            SkillStatus(skill_id=sid, version=1, lifecycle="approved", active=False)
        )

    before_active = {
        (v.skill_id, v.version): s.active for v, s, _st in store.iter_loaded()
    }
    results = schedule_shadow_slots(
        store,
        eval_store=eval_store,
        config=HARSH_AUTONOMY,
        snapshot_id="m5-shadow",
    )
    assert results
    assert len(results) == HARSH_AUTONOMY.shadow_slots_per_task_class
    assert all(r.visible_to_caller is False for r in results)
    assert all(r.success for r in results)  # certification run="true"
    after_active = {
        (v.skill_id, v.version): s.active for v, s, _st in store.iter_loaded()
    }
    assert after_active == before_active

    for result in results:
        stats = store.get_stats(result.skill_id, result.version)
        # Shadow scheduling must not inflate caller-visible predictive trust.
        assert stats.predictive_trust.applications == 0
        assert stats.predictive_trust.successes == 0

    shadow_rows = [
        row
        for row in eval_store.metric_rows(snapshot_id="m5-shadow")
        if row.get("arm") == "shadow"
    ]
    assert len(shadow_rows) == len(results)
    assert all(row.get("skill_id") for row in shadow_rows)

    proposals = schedule_shadow_evaluations(
        store, eval_store=eval_store, config=HARSH_AUTONOMY, snapshot_id="m5-shadow-job"
    )
    assert proposals
    assert all(p.payload.get("visible_to_caller") is False for p in proposals)
    eval_store.close()
