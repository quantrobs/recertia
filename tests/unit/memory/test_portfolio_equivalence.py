"""Differential tests: ``RECERTIA_PORTFOLIO_CONTROLLER`` must not change any observable.

The two implementations of ``recompute_active_set`` are compared on everything a caller or
the store can see: the returned status list (order included), the pressure dict, the final
on-disk active bits, and the exact sequence of ``write_status`` / ``write_stats`` /
``write_retrieval_ablation`` calls. The stores are spied on rather than only diffed at the
end, because a refactor that produces the right final state through a different set of
writes is still a behavior change.

Both branches are exercised, including ``eval_store is not None`` — the branch that does the
most work (fresh contribution estimates, stats writes, class-level ablation write, and the
candidate-pool narrowing) and that no production caller currently reaches.

The last two tests document the two places where the controller *intentionally* differs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts.criteria import (
    CriterionResult,
    SkillCertificationCriterion,
    TaskCriterion,
    mint_rejecting_proof,
)
from contracts.run import RunManifest, RunState, SkillCandidateRef, Task
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from contracts.stats import Contribution, PredictiveTrust, RetrievalAblationEffect, SkillStats
from contracts.status import SkillStatus
from recertia.evals.store import EvalStore
from recertia.memory.procedural.active_set import recompute_active_set
from recertia.memory.procedural.seeds import seed_approved_for_tests
from recertia.memory.procedural.store import SkillStore
from recertia.review.autonomy_config import AutonomyConfig

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_FLAG = "RECERTIA_PORTFOLIO_CONTROLLER"


# ---------------------------------------------------------------------------
# Fixture library
# ---------------------------------------------------------------------------


def _version(skill_id: str, *, version: int = 1, task_class: str = "repo-chore") -> SkillVersion:
    base = SkillCertificationCriterion(id="ok", kind="command", run="true", preregistered=True)
    return SkillVersion(
        skill_id=skill_id,
        version=version,
        title=f"Equivalence fixture {skill_id}",
        intent=f"Intent text long enough for the {skill_id} equivalence fixture version.",
        task_class=task_class,
        steps=[
            Step(
                id="step_1",
                tool="shell",
                intent="Run a trivial shell step for the equivalence fixture",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[
            base.model_copy(
                update={"sensitivity_proof": mint_rejecting_proof(base, fingerprint="equivalence")}
            )
        ],
        provenance=Provenance(
            distilled_from_run="equivalence",
            distilled_at=_NOW,
            curation="human_authored",
            authoring_prior_version="ap-test",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=_NOW),
    )


def _contribution(estimate: float | None, *, applications: int) -> Contribution:
    if estimate is None:
        return Contribution(applications=applications, successes=applications // 2)
    return Contribution(
        applications=applications,
        successes=round(applications * (0.5 + estimate)),
        suppressed_applications=applications,
        suppressed_successes=applications // 2,
    )


@dataclass(frozen=True)
class _Row:
    skill_id: str
    lifecycle: str = "approved"
    version: int = 1
    task_class: str = "repo-chore"
    estimate: float | None = 0.2
    applications: int = 100
    trust: tuple[int, int] = (10, 5)
    last_used_at: datetime | None = None
    active: bool = False


# A deliberately messy library: exact full ties (broken by ascending skill_id in both
# implementations), ties on estimate alone, null estimates, negative estimates, a second
# version of one skill, every non-approved lifecycle, and a second task class with no
# randomized evidence at all so the "no candidates → fall back to approved" branch runs.
_LIBRARY: tuple[_Row, ...] = (
    _Row("eq-a", estimate=0.3, last_used_at=_NOW - timedelta(days=1), active=True),
    _Row("eq-b", estimate=0.3, trust=(10, 9), last_used_at=_NOW - timedelta(days=2)),
    _Row("eq-c", estimate=0.3, last_used_at=_NOW - timedelta(days=1)),
    _Row("eq-h", estimate=0.3, last_used_at=_NOW - timedelta(days=1), active=True),
    _Row("eq-d", estimate=0.1, last_used_at=None),
    _Row("eq-e", estimate=None, trust=(10, 10), applications=60, last_used_at=_NOW),
    _Row("eq-f", estimate=None, trust=(10, 10), applications=60, last_used_at=_NOW),
    _Row("eq-g", estimate=-0.2, trust=(20, 4), applications=200, active=True),
    _Row("multi", version=1, estimate=0.05, applications=40),
    _Row("multi", version=2, estimate=0.45, applications=40),
    _Row("sh-one", lifecycle="shadow", estimate=0.4),
    _Row("bench-one", lifecycle="benched", estimate=-0.5, applications=300),
    _Row("cand-one", lifecycle="candidate"),
    _Row("quar-one", lifecycle="quarantined"),
    _Row("docs-x", task_class="docs-chore", estimate=0.3),
    _Row("docs-y", task_class="docs-chore", estimate=0.1),
    _Row("docs-z", task_class="docs-chore", lifecycle="benched", estimate=None),
)

# Approved repo-chore skills that have randomized evidence in the eval store. The rest end up
# with a None estimate there and are therefore dropped from the candidate pool by the
# orchestrator (not by rank_skills) — the behavior this differential test has to pin down.
_EVIDENCED: dict[tuple[str, int], tuple[tuple[int, int], tuple[int, int]]] = {
    ("eq-a", 1): ((6, 10), (4, 10)),  # +0.2
    ("eq-b", 1): ((8, 10), (4, 10)),  # +0.4
    ("eq-c", 1): ((6, 10), (4, 10)),  # +0.2, a full tie with eq-a after the refresh
    ("eq-g", 1): ((2, 10), (6, 10)),  # -0.4
    ("multi", 2): ((9, 10), (4, 10)),  # +0.5
    ("multi", 1): ((5, 10), (0, 0)),  # shadow arm only → estimate stays None
}


class _SpySkillStore(SkillStore):
    """Records every status/stats write so side effects can be diffed, not just end state."""

    def __init__(self, skills_root: Path | str) -> None:
        super().__init__(skills_root)
        self.status_writes: list[dict] = []
        self.stats_writes: list[dict] = []

    def write_status(self, status: SkillStatus, *, expected_lifecycle: str | None = None) -> Path:
        self.status_writes.append(status.model_dump(mode="json"))
        return super().write_status(status, expected_lifecycle=expected_lifecycle)

    def write_stats(self, stats: SkillStats) -> Path:
        self.stats_writes.append(_stats_payload(stats))
        return super().write_stats(stats)


class _SpyEvalStore(EvalStore):
    def __init__(self, path: Path | str) -> None:
        super().__init__(path)
        self.ablation_writes: list[dict] = []

    def write_retrieval_ablation(self, effect: RetrievalAblationEffect) -> None:
        payload = effect.model_dump(mode="json")
        payload.pop("last_evaluated_at", None)
        self.ablation_writes.append(payload)
        super().write_retrieval_ablation(effect)


def _stats_payload(stats: SkillStats) -> dict:
    """Stats dump with the wall-clock stamp removed.

    ``estimate_contribution`` sets ``last_evaluated_at=datetime.now(...)`` on every pass, so
    it differs between the two runs by construction and says nothing about equivalence.
    """

    payload = stats.model_dump(mode="json")
    payload["contribution"].pop("last_evaluated_at", None)
    return payload


def _build_library(root: Path, rows: tuple[_Row, ...] = _LIBRARY) -> _SpySkillStore:
    store = _SpySkillStore(root)
    for row in rows:
        version = _version(row.skill_id, version=row.version, task_class=row.task_class)
        if row.lifecycle == "approved":
            seed_approved_for_tests(store, version, active=row.active)
        else:
            store.write_version(version)
            store._write_status_unchecked(
                SkillStatus(
                    skill_id=row.skill_id,
                    version=row.version,
                    lifecycle=row.lifecycle,  # type: ignore[arg-type]
                    active=False,
                )
            )
        store.write_stats(
            SkillStats(
                skill_id=row.skill_id,
                version=row.version,
                predictive_trust=PredictiveTrust(
                    applications=row.trust[0],
                    successes=row.trust[1],
                    last_used_at=row.last_used_at,
                ),
                contribution=_contribution(row.estimate, applications=row.applications),
            )
        )
    # Seeding writes are not part of what recompute does.
    store.status_writes.clear()
    store.stats_writes.clear()
    return store


def _observation(
    run_id: str,
    *,
    arm: str,
    task_class: str,
    solved: bool,
    chosen: tuple[str, int] | None = None,
    suppressed: tuple[str, int] | None = None,
) -> RunState:
    criterion = TaskCriterion(id="req", kind="command", run="true", source="caller")
    return RunState(
        run_id=run_id,
        task=Task(
            task_id=run_id,
            request="equivalence evidence fixture",
            task_class=task_class,
            submitted_at=_NOW,
        ),
        manifest=RunManifest(index_snapshot_id="equivalence-snapshot", criteria_hash="locked"),
        arm=arm,  # type: ignore[arg-type]
        criteria=[criterion],
        criteria_locked_at=_NOW,
        chosen=SkillCandidateRef(skill_id=chosen[0], version=chosen[1], score=1.0)
        if chosen
        else None,
        suppressed_skill=SkillCandidateRef(skill_id=suppressed[0], version=suppressed[1], score=1.0)
        if suppressed
        else None,
        attempt_no=1,
        results=[CriterionResult(criterion_id="req", kind="command", passed=solved)],
        terminal="solved" if solved else "unsolved",
    )


def _build_evidence(path: Path) -> _SpyEvalStore:
    store = _SpyEvalStore(path)
    for (skill_id, version), (shadow, suppression) in _EVIDENCED.items():
        successes, trials = shadow
        for i in range(trials):
            store.append_run(
                _observation(
                    f"sh-{skill_id}-{version}-{i}",
                    arm="shadow",
                    task_class="repo-chore",
                    solved=i < successes,
                    chosen=(skill_id, version),
                )
            )
        successes, trials = suppression
        for i in range(trials):
            store.append_run(
                _observation(
                    f"su-{skill_id}-{version}-{i}",
                    arm="control",
                    task_class="repo-chore",
                    solved=i < successes,
                    suppressed=(skill_id, version),
                )
            )
    # Class-level arms so estimate_retrieval_ablation has both samples.
    for i in range(10):
        store.append_run(
            _observation(f"tr-{i}", arm="treatment", task_class="repo-chore", solved=i < 7)
        )
    for i in range(10):
        store.append_run(
            _observation(f"co-{i}", arm="control", task_class="repo-chore", solved=i < 5)
        )
    store.ablation_writes.clear()
    return store


# ---------------------------------------------------------------------------
# Differential comparison
# ---------------------------------------------------------------------------


@dataclass
class _Outcome:
    statuses: list[dict] = field(default_factory=list)
    pressure: dict[str, float] = field(default_factory=dict)
    on_disk: list[tuple[str, str, int, str, bool]] = field(default_factory=list)
    status_writes: list[dict] = field(default_factory=list)
    stats_writes: list[dict] = field(default_factory=list)
    ablation_writes: list[dict] = field(default_factory=list)


def _execute(
    root: Path, *, cap: int, with_eval: bool, rows: tuple[_Row, ...] = _LIBRARY
) -> _Outcome:
    store = _build_library(root / "skills", rows)
    eval_store = _build_evidence(root / "evals.sqlite") if with_eval else None
    try:
        statuses, pressure = recompute_active_set(
            store,
            config=AutonomyConfig(active_cap_per_task_class=cap),
            eval_store=eval_store,
        )
    finally:
        if eval_store is not None:
            eval_store.close()
    return _Outcome(
        statuses=[status.model_dump(mode="json") for status in statuses],
        pressure=pressure,
        on_disk=[
            (version.task_class, version.skill_id, version.version, status.lifecycle, status.active)
            for version, status, _stats in store.iter_loaded()
        ],
        status_writes=store.status_writes,
        stats_writes=store.stats_writes,
        ablation_writes=eval_store.ablation_writes if eval_store is not None else [],
    )


# Caps that straddle every tie group in the fixture, on both orchestrator branches. The
# eval-store branch replays observations into SQLite, so it gets the caps that cut a tie
# group rather than the whole sweep.
_CASES: list[tuple[int, bool]] = [(cap, False) for cap in (0, 1, 2, 3, 4, 5, 50)] + [
    (cap, True) for cap in (0, 1, 3, 4, 50)
]


@pytest.mark.parametrize(
    ("cap", "with_eval"),
    _CASES,
    ids=[f"cap{cap}-{'eval' if with_eval else 'no-eval'}" for cap, with_eval in _CASES],
)
def test_controller_path_matches_legacy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: int, with_eval: bool
) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    legacy = _execute(tmp_path / "legacy", cap=cap, with_eval=with_eval)

    monkeypatch.setenv(_FLAG, "1")
    controller = _execute(tmp_path / "controller", cap=cap, with_eval=with_eval)

    assert controller.pressure == legacy.pressure
    assert controller.statuses == legacy.statuses
    assert controller.on_disk == legacy.on_disk
    assert controller.status_writes == legacy.status_writes
    assert controller.stats_writes == legacy.stats_writes
    assert controller.ablation_writes == legacy.ablation_writes


@pytest.mark.parametrize("with_eval", [False, True], ids=["no-eval-store", "eval-store"])
def test_differential_fixture_is_not_vacuous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_eval: bool
) -> None:
    """Guard the comparison above: the fixture must actually flip bits and write."""

    monkeypatch.delenv(_FLAG, raising=False)
    outcome = _execute(tmp_path / "legacy", cap=3, with_eval=with_eval)
    active = {
        (sid, ver)
        for tc, sid, ver, _lc, is_active in outcome.on_disk
        if tc == "repo-chore" and is_active
    }
    approved = {
        (sid, ver)
        for tc, sid, ver, lifecycle, _a in outcome.on_disk
        if tc == "repo-chore" and lifecycle == "approved"
    }
    # The cap has to actually bind in repo-chore, or the comparison proves nothing.
    assert 0 < len(active) <= 3 < len(approved)
    assert outcome.pressure["repo-chore"] > 0
    assert outcome.status_writes, "no active bit ever flipped; the fixture proves nothing"
    if with_eval:
        assert len(outcome.ablation_writes) == 2, "one class-level ablation write per task class"
        assert outcome.stats_writes, "fresh contribution estimates were never persisted"
    else:
        assert outcome.stats_writes == []
        assert outcome.ablation_writes == []


def test_eval_evidence_fixture_covers_both_candidate_pool_outcomes(tmp_path: Path) -> None:
    """The eval fixture must produce both estimated and null-estimate approved skills."""

    eval_store = _build_evidence(tmp_path / "evals.sqlite")
    try:
        bulk = eval_store.contribution_samples_bulk(task_class="repo-chore")
        both_arms = {key for key, (sh, su) in bulk.items() if sh.trials and su.trials}
        one_arm = {key for key, (sh, su) in bulk.items() if not (sh.trials and su.trials)}
        assert ("eq-a", 1) in both_arms
        assert ("multi", 1) in one_arm  # shadow only → estimate None → not a candidate
        assert ("eq-d", 1) not in bulk  # approved but wholly unevidenced
        # The other task class has no randomized evidence, so the fallback branch runs there.
        assert eval_store.contribution_samples_bulk(task_class="docs-chore") == {}
    finally:
        eval_store.close()


def test_controller_never_benches_a_retirement_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``propose_retirements`` is not wired to writes in Phase 1 (Curator wiring is Phase 5)."""

    monkeypatch.setenv(_FLAG, "1")
    store = _build_library(tmp_path / "skills")
    recompute_active_set(store, config=AutonomyConfig(evidence_floor=1, retirement_threshold=0.0))
    for _version_, status, _stats in store.iter_loaded():
        assert status.retirement.benched_at is None
        assert status.retirement.reason is None
    lifecycles = {
        (version.skill_id, version.version): status.lifecycle
        for version, status, _stats in store.iter_loaded()
    }
    # eq-g has a clearly negative estimate past the floor and is still approved.
    assert lifecycles[("eq-g", 1)] == "approved"
    assert lifecycles[("bench-one", 1)] == "benched"  # unchanged, not re-benched


# ---------------------------------------------------------------------------
# Intended differences (documented, not asserted as equivalence)
# ---------------------------------------------------------------------------


def _two_way_actives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: tuple[_Row, ...], *, cap: int
) -> tuple[set[tuple[str, int]], set[tuple[str, int]]]:
    monkeypatch.delenv(_FLAG, raising=False)
    legacy = _execute(tmp_path / "legacy", cap=cap, with_eval=False, rows=rows)
    monkeypatch.setenv(_FLAG, "1")
    controller = _execute(tmp_path / "controller", cap=cap, with_eval=False, rows=rows)
    return (
        {(sid, ver) for _tc, sid, ver, _lc, active in legacy.on_disk if active},
        {(sid, ver) for _tc, sid, ver, _lc, active in controller.on_disk if active},
    )


def test_recency_breaks_estimate_and_trust_ties_only_under_the_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one intended ranking change: a real tiebreak instead of enumeration order.

    Legacy ranks on ``(estimate, trust)`` only, so a full tie is resolved by the order
    ``SkillStore.list_versions`` happens to yield — ascending ``skill_id``. The controller
    consults recency next, which specs §24.1 names as the third ranking component.
    """

    rows = (
        _Row("aa-stale", estimate=0.2, last_used_at=_NOW - timedelta(days=10)),
        _Row("zz-fresh", estimate=0.2, last_used_at=_NOW),
    )
    legacy_active, controller_active = _two_way_actives(tmp_path, monkeypatch, rows, cap=1)
    assert legacy_active == {("aa-stale", 1)}
    assert controller_active == {("zz-fresh", 1)}


def test_version_tiebreak_is_numeric_not_lexicographic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``v2`` before ``v10``: the controller compares versions as integers.

    Legacy inherits the directory walk's string ordering, which puts ``v10`` first.
    """

    rows = (
        _Row("dup", version=2, estimate=0.2, last_used_at=_NOW),
        _Row("dup", version=10, estimate=0.2, last_used_at=_NOW),
    )
    legacy_active, controller_active = _two_way_actives(tmp_path, monkeypatch, rows, cap=1)
    assert legacy_active == {("dup", 10)}
    assert controller_active == {("dup", 2)}
