"""M5 done-when suite: shadow autonomy, quarantine, retirement, active-set cap."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import CriterionResult, SensitivityProof, SkillCertificationCriterion, TaskCriterion
from contracts.run import RunManifest, RunState, SkillCandidateRef, Task
from contracts.skill import Hygiene, Provenance, SkillUse, SkillVersion, Step
from contracts.stats import Contribution, SkillStats, Trust
from contracts.status import SkillStatus
from fandea.ledger import HashChainLedger
from fandea.evals.store import EvalStore
from fandea.memory.procedural.active_set import recompute_active_set
from fandea.memory.procedural.store import SkillStore
from fandea.review.autonomy_config import DEFAULT_AUTONOMY, HARSH_AUTONOMY
from fandea.review.lifecycle import (
    LifecycleError,
    maybe_auto_promote_from_shadow,
    maybe_bench_on_contribution,
    quarantine_on_failures,
    restore_benched,
)
from fandea.review.shadow import record_shadow_outcome


def _skill(
    skill_id: str,
    *,
    task_class: str = "repo-chore",
    uses: list[SkillUse] | None = None,
) -> SkillVersion:
    proof = SensitivityProof(
        criterion_id="ok",
        negative_fixture="empty",
        rejected=True,
        checked_at=datetime.now(timezone.utc),
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
            SkillCertificationCriterion(
                id="ok",
                kind="command",
                run="true",
                sensitivity_proof=proof,
                preregistered=True,
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
    treatment: tuple[int, int],
    control: tuple[int, int],
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
                attempt_no=1,
                results=[CriterionResult(criterion_id=criterion.id, kind="command", passed=success)],
                terminal="solved" if success else "unsolved",
            )
        )

    successes, trials = treatment
    for index in range(trials):
        append(f"{prefix}-t-{index}", "treatment", index < successes, True)
    successes, trials = control
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
        treatment=(10, 10),
        control=(5, 10),
    )
    approved = maybe_auto_promote_from_shadow(
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
        treatment=(10, 10),
        control=(10, 10),
    )
    with pytest.raises(LifecycleError, match="refusing auto-promote"):
        maybe_auto_promote_from_shadow(store, "zero-lift", 1, eval_store=zero_eval_store)
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
            trust=Trust(applications=5, successes=0),
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
        treatment=(5, 40),
        control=(32, 40),
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
            # 25 apps, 10 successes vs baseline 0.5 → mild negative/near-zero
            _record_evidence(
                eval_store,
                skill_id=sid,
                prefix=sid,
                treatment=(10, 25),
                control=(13, 25),
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
        _seed(store, _skill(sid), lifecycle="approved")
        store.write_status(
            SkillStatus(skill_id=sid, version=1, lifecycle="approved", active=True)
        )
        store.write_stats(
            SkillStats(
                skill_id=sid,
                version=1,
                trust=Trust(applications=10 + i, successes=5 + i),
                contribution=Contribution(
                    applications=10 + i, successes=5 + i, baseline_success=0.3
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
