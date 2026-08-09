"""Property tests for the pure Causal Skill Portfolio controller (Phase 1, §5).

Hand-rolled deterministic loops and full permutation sweeps rather than a property-testing
library: the repo has no hypothesis dependency and these input spaces are small enough to
enumerate exhaustively.
"""

from __future__ import annotations

import dataclasses
import inspect
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from contracts.criteria import SkillCertificationCriterion, mint_rejecting_proof
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from contracts.stats import Contribution, PredictiveTrust, SkillStats
from contracts.status import SkillStatus
from recertia.memory.procedural import portfolio
from recertia.memory.procedural.portfolio import (
    PortfolioRankItem,
    RetirementProposal,
    propose_retirements,
    rank_skills,
    select_active,
)
from recertia.review.autonomy_config import DEFAULT_AUTONOMY, HARSH_AUTONOMY, AutonomyConfig

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _version(skill_id: str, *, version: int = 1, task_class: str = "repo-chore") -> SkillVersion:
    base = SkillCertificationCriterion(id="ok", kind="command", run="true", preregistered=True)
    return SkillVersion(
        skill_id=skill_id,
        version=version,
        title=f"Portfolio fixture {skill_id}",
        intent=f"Intent text long enough for the {skill_id} portfolio ranking fixture.",
        task_class=task_class,
        steps=[
            Step(
                id="step_1",
                tool="shell",
                intent="Run a trivial shell step for the portfolio fixture",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[
            base.model_copy(
                update={"sensitivity_proof": mint_rejecting_proof(base, fingerprint="portfolio")}
            )
        ],
        provenance=Provenance(
            distilled_from_run="portfolio",
            distilled_at=_NOW,
            curation="human_authored",
            authoring_prior_version="ap-test",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=_NOW),
    )


def _contribution(
    estimate: float | None,
    *,
    applications: int = 100,
) -> Contribution:
    """A ``Contribution`` whose computed ``estimate`` is ``estimate``.

    ``None`` is produced the way production produces it — by leaving the suppression arm
    empty, which is the Blind Curator nullity (specs §24.2), not by storing a sentinel.
    """

    if estimate is None:
        return Contribution(applications=applications, successes=applications // 2)
    return Contribution(
        applications=applications,
        successes=round(applications * (0.5 + estimate)),
        suppressed_applications=applications,
        suppressed_successes=applications // 2,
    )


def _candidate(
    skill_id: str,
    *,
    version: int = 1,
    estimate: float | None = 0.1,
    applications: int = 100,
    trust_applications: int = 10,
    trust_successes: int = 5,
    last_used_at: datetime | None = None,
) -> tuple[SkillVersion, SkillStatus, SkillStats]:
    return (
        _version(skill_id, version=version),
        SkillStatus(skill_id=skill_id, version=version, lifecycle="candidate"),
        SkillStats(
            skill_id=skill_id,
            version=version,
            predictive_trust=PredictiveTrust(
                applications=trust_applications,
                successes=trust_successes,
                last_used_at=last_used_at,
            ),
            contribution=_contribution(estimate, applications=applications),
        ),
    )


def _ids(items: list[PortfolioRankItem]) -> list[tuple[str, int]]:
    return [(item.skill_id, item.version) for item in items]


# ---------------------------------------------------------------------------
# Determinism / total order
# ---------------------------------------------------------------------------


def test_rank_skills_is_deterministic_across_repeated_calls() -> None:
    candidates = [
        _candidate("det-a", estimate=0.3),
        _candidate("det-b", estimate=None),
        _candidate("det-c", estimate=0.3, trust_successes=9, trust_applications=10),
        _candidate("det-d", estimate=-0.2, last_used_at=_NOW),
    ]
    first = rank_skills(candidates, DEFAULT_AUTONOMY)
    for _ in range(5):
        assert rank_skills(candidates, DEFAULT_AUTONOMY) == first


def test_rank_skills_is_shuffle_invariant_over_every_permutation() -> None:
    candidates = [
        _candidate("perm-a", estimate=0.3),
        _candidate("perm-b", estimate=0.3),  # exact tie with perm-a on every component
        _candidate("perm-c", estimate=None),
        _candidate("perm-d", estimate=None, last_used_at=_NOW),
        _candidate("perm-e", estimate=-0.1, trust_successes=10, trust_applications=10),
    ]
    expected = _ids(rank_skills(candidates, DEFAULT_AUTONOMY))
    for permutation in itertools.permutations(candidates):
        assert _ids(rank_skills(list(permutation), DEFAULT_AUTONOMY)) == expected


def test_rank_skills_returns_every_candidate_exactly_once() -> None:
    candidates = [_candidate(f"keep-{i}", estimate=None if i % 2 else 0.1) for i in range(8)]
    ranked = rank_skills(candidates, DEFAULT_AUTONOMY)
    assert len(ranked) == len(candidates)
    assert sorted(_ids(ranked)) == sorted((v.skill_id, v.version) for v, _s, _st in candidates)


# ---------------------------------------------------------------------------
# Ranking order: estimate > trust > recency > applications > (skill_id, version)
# ---------------------------------------------------------------------------


def test_estimate_dominates_predictive_trust() -> None:
    strong_estimate = _candidate(
        "dom-low-trust", estimate=0.4, trust_applications=10, trust_successes=0
    )
    strong_trust = _candidate(
        "dom-high-trust", estimate=0.1, trust_applications=10, trust_successes=10
    )
    assert _ids(rank_skills([strong_trust, strong_estimate], DEFAULT_AUTONOMY)) == [
        ("dom-low-trust", 1),
        ("dom-high-trust", 1),
    ]


def test_predictive_trust_dominates_recency() -> None:
    trusted_but_stale = _candidate(
        "trust-stale",
        estimate=0.2,
        trust_applications=10,
        trust_successes=10,
        last_used_at=_NOW - timedelta(days=30),
    )
    fresh_but_untrusted = _candidate(
        "trust-fresh",
        estimate=0.2,
        trust_applications=10,
        trust_successes=1,
        last_used_at=_NOW,
    )
    assert _ids(rank_skills([fresh_but_untrusted, trusted_but_stale], DEFAULT_AUTONOMY)) == [
        ("trust-stale", 1),
        ("trust-fresh", 1),
    ]


def test_recency_dominates_applications() -> None:
    recent_but_rarely_used = _candidate(
        "rec-fresh", estimate=0.2, applications=40, last_used_at=_NOW
    )
    heavily_used_but_stale = _candidate(
        "rec-stale", estimate=0.2, applications=400, last_used_at=_NOW - timedelta(days=1)
    )
    assert _ids(rank_skills([heavily_used_but_stale, recent_but_rarely_used], DEFAULT_AUTONOMY)) == [
        ("rec-fresh", 1),
        ("rec-stale", 1),
    ]


def test_never_used_sorts_after_used_without_comparing_none_to_datetime() -> None:
    used = _candidate("recency-used", estimate=0.2, last_used_at=_NOW - timedelta(days=999))
    never_used = _candidate("recency-never", estimate=0.2, last_used_at=None)
    assert _ids(rank_skills([never_used, used], DEFAULT_AUTONOMY)) == [
        ("recency-used", 1),
        ("recency-never", 1),
    ]


def test_naive_last_used_at_is_read_as_utc_and_does_not_raise() -> None:
    naive = _candidate("naive-recent", estimate=0.2, last_used_at=datetime(2026, 6, 1))
    aware = _candidate(
        "aware-older", estimate=0.2, last_used_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert _ids(rank_skills([aware, naive], DEFAULT_AUTONOMY)) == [
        ("naive-recent", 1),
        ("aware-older", 1),
    ]


def test_applications_breaks_ties_after_recency() -> None:
    many = _candidate("apps-many", estimate=0.2, applications=200, last_used_at=_NOW)
    few = _candidate("apps-few", estimate=0.2, applications=100, last_used_at=_NOW)
    assert _ids(rank_skills([few, many], DEFAULT_AUTONOMY)) == [
        ("apps-many", 1),
        ("apps-few", 1),
    ]


def test_final_tiebreak_is_ascending_skill_id_then_numeric_version() -> None:
    # Everything ties, so only the identity tiebreak is left. skill_id ascends while every
    # numeric component descends, which is why the key cannot be a single reverse=True sort.
    candidates = [
        _candidate("tie-b", version=2, estimate=0.2),
        _candidate("tie-a", version=10, estimate=0.2),
        _candidate("tie-a", version=2, estimate=0.2),
    ]
    assert _ids(rank_skills(candidates, DEFAULT_AUTONOMY)) == [
        ("tie-a", 2),
        ("tie-a", 10),  # integer order: v2 before v10, unlike a string-sorted directory walk
        ("tie-b", 2),
    ]


def test_none_estimate_is_demoted_to_the_bottom_but_never_dropped() -> None:
    # FR-2: below-floor / unmeasured skills stay in the pool, demoted only by the None estimate.
    candidates = [
        _candidate("floor-unmeasured", estimate=None, trust_applications=10, trust_successes=10),
        _candidate("floor-negative", estimate=-0.4, applications=1, trust_successes=0),
        _candidate("floor-positive", estimate=0.1),
    ]
    ranked = rank_skills(candidates, DEFAULT_AUTONOMY)
    assert _ids(ranked) == [("floor-positive", 1), ("floor-negative", 1), ("floor-unmeasured", 1)]
    assert ranked[-1].contribution_estimate is None
    assert ranked[-1].score == float("-inf")


def test_unmeasured_skills_are_ordered_among_themselves_by_trust() -> None:
    low = _candidate("null-low", estimate=None, trust_applications=10, trust_successes=1)
    high = _candidate("null-high", estimate=None, trust_applications=10, trust_successes=9)
    assert _ids(rank_skills([low, high], DEFAULT_AUTONOMY)) == [
        ("null-high", 1),
        ("null-low", 1),
    ]


def test_rank_item_fields_come_from_the_documented_sources() -> None:
    candidate = _candidate(
        "fields-demo",
        estimate=0.25,
        applications=80,
        trust_applications=40,
        trust_successes=30,
        last_used_at=_NOW,
    )
    (item,) = rank_skills([candidate], DEFAULT_AUTONOMY)
    stats = candidate[2]
    assert item.contribution_estimate == pytest.approx(0.25)
    # applications is the contribution (shadow-arm) count, not predictive_trust.applications.
    assert item.applications == stats.contribution.applications == 80
    assert item.applications != stats.predictive_trust.applications
    assert item.predictive_trust == pytest.approx(stats.predictive_trust.score)
    assert item.last_used_at == stats.predictive_trust.last_used_at
    assert item.score == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# select_active
# ---------------------------------------------------------------------------


def test_select_active_respects_the_cap() -> None:
    ranked = rank_skills(
        [_candidate(f"cap-{i}", estimate=0.5 - i / 10) for i in range(6)],
        DEFAULT_AUTONOMY,
    )
    assert select_active(ranked, 3) == {("cap-0", 1), ("cap-1", 1), ("cap-2", 1)}
    for cap in range(0, 9):
        assert len(select_active(ranked, cap)) == min(max(cap, 0), len(ranked))


def test_select_active_admits_nobody_for_a_non_positive_cap() -> None:
    ranked = rank_skills([_candidate("zero-a"), _candidate("zero-b")], DEFAULT_AUTONOMY)
    assert select_active(ranked, 0) == set()
    assert select_active(ranked, -1) == set()


# ---------------------------------------------------------------------------
# propose_retirements
# ---------------------------------------------------------------------------


def _item(
    skill_id: str,
    *,
    estimate: float | None,
    applications: int,
    version: int = 1,
) -> PortfolioRankItem:
    return PortfolioRankItem(
        skill_id=skill_id,
        version=version,
        contribution_estimate=estimate,
        predictive_trust=0.5,
        applications=applications,
        last_used_at=None,
        score=estimate if estimate is not None else float("-inf"),
    )


def test_retirement_is_inclusive_at_the_threshold_boundary() -> None:
    floor = DEFAULT_AUTONOMY.evidence_floor
    at_boundary = _item("bd-at", estimate=-DEFAULT_AUTONOMY.retirement_threshold, applications=floor)
    just_inside = _item("bd-in", estimate=-0.2, applications=floor)
    just_outside = _item("bd-out", estimate=-0.04, applications=floor)
    proposals = propose_retirements(
        [at_boundary, just_inside, just_outside], DEFAULT_AUTONOMY
    )
    assert [p.skill_id for p in proposals] == ["bd-at", "bd-in"]
    assert all(p.reason == "negative_contribution" for p in proposals)


def test_harsh_autonomy_retires_an_estimate_of_exactly_zero() -> None:
    assert HARSH_AUTONOMY.retirement_threshold == 0.0
    floor = HARSH_AUTONOMY.evidence_floor
    proposals = propose_retirements(
        [
            _item("harsh-zero", estimate=0.0, applications=floor),
            _item("harsh-positive", estimate=0.01, applications=floor),
        ],
        HARSH_AUTONOMY,
    )
    assert [p.skill_id for p in proposals] == ["harsh-zero"]


def test_retirement_refuses_below_the_evidence_floor() -> None:
    floor = DEFAULT_AUTONOMY.evidence_floor
    proposals = propose_retirements(
        [
            _item("below", estimate=-0.9, applications=floor - 1),
            _item("at-floor", estimate=-0.9, applications=floor),
        ],
        DEFAULT_AUTONOMY,
    )
    assert [p.skill_id for p in proposals] == ["at-floor"]


def test_retirement_refuses_a_null_estimate_however_many_applications() -> None:
    # Blind Curator nullity: no randomized suppression arm, no retirement.
    assert propose_retirements([_item("null", estimate=None, applications=10_000)], HARSH_AUTONOMY) == []


def test_retirement_proposal_carries_the_lifecycle_evidence_string() -> None:
    item = _item("ev", estimate=-0.375, applications=DEFAULT_AUTONOMY.evidence_floor)
    assert propose_retirements([item], DEFAULT_AUTONOMY) == [
        RetirementProposal(
            skill_id="ev",
            version=1,
            reason="negative_contribution",
            evidence="estimate=-0.375",
            contribution_estimate=-0.375,
            applications=DEFAULT_AUTONOMY.evidence_floor,
        )
    ]


def test_retirement_matches_the_lifecycle_bench_guard_over_a_grid() -> None:
    """Same operators, same boundary as ``maybe_bench_on_contribution``'s guard."""

    configs = [DEFAULT_AUTONOMY, HARSH_AUTONOMY, AutonomyConfig(evidence_floor=0)]
    estimates: list[float | None] = [None, -1.0, -0.25, -0.05, 0.0, 0.05, 0.5]
    for config in configs:
        for applications in (0, 1, config.evidence_floor - 1, config.evidence_floor, 500):
            if applications < 0:
                continue
            for estimate in estimates:
                item = _item("grid", estimate=estimate, applications=applications)
                # Transcribed from review/lifecycle.py: raise below the floor, then raise
                # unless the estimate is present and negative enough.
                benchable = not (
                    applications < config.evidence_floor
                    or estimate is None
                    or estimate > -config.retirement_threshold
                )
                assert bool(propose_retirements([item], config)) is benchable


def test_retirement_never_proposes_for_cap_pressure() -> None:
    # A whole class of healthy, heavily-evidenced skills over any cap yields no proposals.
    ranked = rank_skills(
        [_candidate(f"press-{i}", estimate=0.3, applications=500) for i in range(10)],
        HARSH_AUTONOMY,
    )
    assert select_active(ranked, HARSH_AUTONOMY.active_cap_per_task_class) != set()
    assert propose_retirements(ranked, HARSH_AUTONOMY) == []


# ---------------------------------------------------------------------------
# Extension points (FR-8, §3.7): present, documented, dormant.
# ---------------------------------------------------------------------------


def test_rank_item_exposes_a_fidelity_extension_point_defaulting_to_none() -> None:
    field = {f.name: f for f in dataclasses.fields(PortfolioRankItem)}["fidelity"]
    assert field.default is None
    (item,) = rank_skills([_candidate("fidelity-demo")], DEFAULT_AUTONOMY)
    assert item.fidelity is None
    assert dataclasses.replace(item, fidelity="crystal").fidelity == "crystal"


def test_score_fn_extension_point_overrides_the_default_order() -> None:
    strong_estimate = _candidate(
        "sf-estimate", estimate=0.4, trust_applications=10, trust_successes=0
    )
    strong_trust = _candidate("sf-trust", estimate=0.1, trust_applications=10, trust_successes=10)
    candidates = [strong_estimate, strong_trust]

    assert _ids(rank_skills(candidates, DEFAULT_AUTONOMY)) == [("sf-estimate", 1), ("sf-trust", 1)]

    ranked = rank_skills(candidates, DEFAULT_AUTONOMY, score_fn=lambda item: item.predictive_trust)
    assert _ids(ranked) == [("sf-trust", 1), ("sf-estimate", 1)]
    assert [item.score for item in ranked] == [item.predictive_trust for item in ranked]


def test_score_fn_can_read_the_default_composite_score() -> None:
    seen: list[float] = []

    def score_fn(item: PortfolioRankItem) -> float:
        seen.append(item.score)
        return -item.score if item.score != float("-inf") else float("-inf")

    candidates = [_candidate("read-a", estimate=0.4), _candidate("read-b", estimate=0.1)]
    ranked = rank_skills(candidates, DEFAULT_AUTONOMY, score_fn=score_fn)
    assert sorted(seen) == pytest.approx([0.1, 0.4])
    assert _ids(ranked) == [("read-b", 1), ("read-a", 1)]


def test_score_fn_ranking_is_still_deterministic_and_shuffle_invariant() -> None:
    candidates = [_candidate(f"sfdet-{i}", estimate=0.1 * (i % 2)) for i in range(4)]

    def score_fn(_item: PortfolioRankItem) -> float:
        return 1.0  # every item ties, so only the tiebreak chain orders them

    expected = _ids(rank_skills(candidates, DEFAULT_AUTONOMY, score_fn=score_fn))
    for permutation in itertools.permutations(candidates):
        assert _ids(rank_skills(list(permutation), DEFAULT_AUTONOMY, score_fn=score_fn)) == expected


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_portfolio_module_imports_no_stores_clock_or_environment() -> None:
    names = vars(portfolio)
    assert "os" not in names
    assert "SkillStore" not in names
    assert "EvalStore" not in names
    # datetime is imported for type hints and tz normalization only; no clock is ever read.
    assert "datetime.now" not in inspect.getsource(portfolio)


def test_ranking_does_not_mutate_its_inputs() -> None:
    candidates = [_candidate("pure-b", estimate=0.1), _candidate("pure-a", estimate=0.9)]
    before = [(v.skill_id, v.version) for v, _s, _st in candidates]
    snapshot = [st.model_dump() for _v, _s, st in candidates]
    rank_skills(candidates, DEFAULT_AUTONOMY)
    assert [(v.skill_id, v.version) for v, _s, _st in candidates] == before
    assert [st.model_dump() for _v, _s, st in candidates] == snapshot
