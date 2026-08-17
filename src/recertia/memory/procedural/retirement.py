"""Single retirement predicate (ADR-0006). Two adapters, one decision.

``propose_retirements`` is the pure adapter (no I/O).
``maybe_bench_on_contribution`` is the effectful adapter (writes lifecycle).
``recompute_active_set`` must not call this — cap membership is not benching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RetirementAction = Literal["below_floor", "no_estimate", "keep", "retire"]


@dataclass(frozen=True)
class RetirementDecision:
    """What the bench predicate concluded. Never a write."""

    action: RetirementAction
    estimate: float | None
    applications: int
    evidence: str | None = None

    @property
    def should_retire(self) -> bool:
        return self.action == "retire"


def retirement_decision(
    *,
    applications: int,
    estimate: float | None,
    evidence_floor: int,
    tau: float,
) -> RetirementDecision:
    """Bench when, and only when, evidence is past the floor and ``estimate <= -tau``.

    These are exactly the conditions both adapters already enforced, boundary included:
    ``tau == 0.0`` makes an estimate of exactly ``0.0`` retirable.
    """

    if applications < evidence_floor:
        return RetirementDecision(
            action="below_floor",
            estimate=estimate,
            applications=applications,
        )
    if estimate is None:
        return RetirementDecision(
            action="no_estimate",
            estimate=None,
            applications=applications,
        )
    if estimate > -tau:
        return RetirementDecision(
            action="keep",
            estimate=estimate,
            applications=applications,
            evidence=f"estimate={estimate}",
        )
    return RetirementDecision(
        action="retire",
        estimate=estimate,
        applications=applications,
        evidence=f"estimate={estimate}",
    )
