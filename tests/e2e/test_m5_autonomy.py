"""M5 done-when suite: shadow autonomy, quarantine, retirement, active-set cap."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance, SkillUse, SkillVersion, Step
from contracts.stats import Contribution, SkillStats, Trust
from contracts.status import SkillStatus
from fandea.ledger import HashChainLedger
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


def test_shadow_auto_promote_requires_lift(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    _seed(store, _skill("shadow-winner"))
    for _ in range(10):
        record_shadow_outcome(store, "shadow-winner", 1, success=True)
    # baseline 0.5 → lift ~0.5
    approved = maybe_auto_promote_from_shadow(
        store, "shadow-winner", 1, baseline_success=0.5, ledger=ledger
    )
    assert approved.lifecycle == "candidate"
    assert approved.active is False

    # High trust, zero lift → refuse
    _seed(store, _skill("zero-lift"))
    for _ in range(10):
        record_shadow_outcome(store, "zero-lift", 1, success=True)
    with pytest.raises(LifecycleError, match="refusing auto-promote"):
        maybe_auto_promote_from_shadow(store, "zero-lift", 1, baseline_success=1.0)


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
            store, "neg-contrib", 1, baseline_success=0.8, config=DEFAULT_AUTONOMY
        )

    # Past floor with sustained negative contribution
    store.write_stats(
        SkillStats(
            skill_id="neg-contrib",
            version=1,
            trust=Trust(applications=40, successes=5),
            contribution=Contribution(applications=40, successes=5),
        )
    )
    benched = maybe_bench_on_contribution(
        store, "neg-contrib", 1, baseline_success=0.8, ledger=ledger
    )
    assert benched.lifecycle == "benched"
    restored = restore_benched(store, "neg-contrib", 1, ledger=ledger)
    assert restored.lifecycle == "candidate"
    assert restored.retirement.restored_at is not None


def test_harsh_config_over_prunes_vs_defaults(tmp_path: Path) -> None:
    """Synthetic harsh config (floor 20, threshold 0) benches more than defaults."""

    def setup(root: Path, config_name: str) -> int:
        store = SkillStore(root / config_name)
        benched = 0
        for i in range(5):
            sid = f"skill-{config_name}-{i}"
            _seed(store, _skill(sid), lifecycle="approved")
            # 25 apps, 10 successes vs baseline 0.5 → mild negative/near-zero
            store.write_stats(
                SkillStats(
                    skill_id=sid,
                    version=1,
                    trust=Trust(applications=25, successes=10),
                    contribution=Contribution(applications=25, successes=10),
                )
            )
            cfg = HARSH_AUTONOMY if config_name == "harsh" else DEFAULT_AUTONOMY
            try:
                maybe_bench_on_contribution(
                    store, sid, 1, baseline_success=0.5, config=cfg
                )
                benched += 1
            except LifecycleError:
                pass
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
