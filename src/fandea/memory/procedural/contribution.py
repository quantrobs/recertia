"""Contribution estimates vs task-class control baselines (specs §24.2, M5)."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.eval import BinomialSample
from contracts.stats import Contribution
from fandea.evals.statistics import newcombe_wilson_difference


def estimate_contribution(
    *,
    applications: int,
    successes: int,
    control: BinomialSample | None,
    has_required_non_judge: bool = True,
) -> Contribution:
    """Return contribution from observed treatment and control samples only."""

    if (
        not has_required_non_judge
        or applications == 0
        or control is None
        or control.trials == 0
    ):
        return Contribution(
            applications=applications,
            successes=successes,
            baseline_success=control.rate if control else None,
            last_evaluated_at=datetime.now(timezone.utc),
        )
    interval = newcombe_wilson_difference(
        BinomialSample(successes=successes, trials=applications),
        control,
    )
    return Contribution(
        applications=applications,
        successes=successes,
        baseline_success=control.rate,
        interval_low=interval.low if interval else None,
        interval_high=interval.high if interval else None,
        last_evaluated_at=datetime.now(timezone.utc),
    )


def trust_score(*, applications: int, successes: int) -> float:
    return (successes + 1) / (applications + 2)
