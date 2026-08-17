"""The bench predicate is one function; adapters must agree with it."""

from __future__ import annotations

from recertia.memory.procedural.portfolio import propose_retirements
from recertia.memory.procedural.retirement import retirement_decision
from recertia.review.autonomy_config import DEFAULT_AUTONOMY, HARSH_AUTONOMY, AutonomyConfig
from tests.unit.memory.test_portfolio import _item


def test_below_floor_never_retires() -> None:
    decision = retirement_decision(
        applications=DEFAULT_AUTONOMY.evidence_floor - 1,
        estimate=-0.9,
        evidence_floor=DEFAULT_AUTONOMY.evidence_floor,
        tau=DEFAULT_AUTONOMY.retirement_threshold,
    )
    assert decision.action == "below_floor"
    assert not decision.should_retire


def test_null_estimate_never_retires() -> None:
    decision = retirement_decision(
        applications=10_000,
        estimate=None,
        evidence_floor=DEFAULT_AUTONOMY.evidence_floor,
        tau=DEFAULT_AUTONOMY.retirement_threshold,
    )
    assert decision.action == "no_estimate"
    assert not decision.should_retire


def test_negative_enough_retires() -> None:
    decision = retirement_decision(
        applications=DEFAULT_AUTONOMY.evidence_floor,
        estimate=-DEFAULT_AUTONOMY.retirement_threshold,
        evidence_floor=DEFAULT_AUTONOMY.evidence_floor,
        tau=DEFAULT_AUTONOMY.retirement_threshold,
    )
    assert decision.should_retire
    assert decision.evidence == f"estimate={-DEFAULT_AUTONOMY.retirement_threshold}"


def test_adapters_agree_on_the_grid() -> None:
    configs = [DEFAULT_AUTONOMY, HARSH_AUTONOMY, AutonomyConfig(evidence_floor=0)]
    estimates: list[float | None] = [None, -1.0, -0.25, -0.05, 0.0, 0.05, 0.5]
    for config in configs:
        for applications in (0, 1, config.evidence_floor - 1, config.evidence_floor, 500):
            if applications < 0:
                continue
            for estimate in estimates:
                decision = retirement_decision(
                    applications=applications,
                    estimate=estimate,
                    evidence_floor=config.evidence_floor,
                    tau=config.retirement_threshold,
                )
                proposed = propose_retirements(
                    [_item("grid", estimate=estimate, applications=applications)],
                    config,
                )
                assert bool(proposed) is decision.should_retire
