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
    baseline_success: float | None,
    has_required_non_judge: bool = True,
) -> Contribution:
    """Return contribution; ``estimate`` is None when inestimable (no baseline / no criterion)."""

    if not has_required_non_judge or applications == 0 or baseline_success is None:
        return Contribution(
            applications=applications,
            successes=successes,
            baseline_success=baseline_success,
            last_evaluated_at=datetime.now(timezone.utc),
        )
    # Approximate control trials so Newcombe CI is defined for the difference.
    control_trials = max(applications, 30)
    control_successes = int(round(baseline_success * control_trials))
    interval = newcombe_wilson_difference(
        BinomialSample(successes=successes, trials=applications),
        BinomialSample(successes=control_successes, trials=control_trials),
    )
    return Contribution(
        applications=applications,
        successes=successes,
        baseline_success=baseline_success,
        interval_low=interval.low if interval else None,
        interval_high=interval.high if interval else None,
        last_evaluated_at=datetime.now(timezone.utc),
    )


def trust_score(*, applications: int, successes: int) -> float:
    return (successes + 1) / (applications + 2)
