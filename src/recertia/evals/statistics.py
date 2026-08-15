"""Binomial Wilson intervals, causal lift, and calibration scoring (specs §19, §23)."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from contracts.eval import (
    BinomialSample,
    CausalLiftResult,
    ConfidenceInterval,
    LiftStatus,
)


def _z_for(level: float) -> float:
    # Common levels without pulling in SciPy.
    table = {0.90: 1.6448536269514722, 0.95: 1.959963984540054, 0.99: 2.5758293035489004}
    if level not in table:
        raise ValueError(f"unsupported confidence level {level}; use one of {sorted(table)}")
    return table[level]


def wilson_interval(
    successes: int, trials: int, *, level: float = 0.95
) -> ConfidenceInterval | None:
    """Single-proportion Wilson score interval."""

    if trials <= 0:
        return None
    z = _z_for(level)
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    centre = (p + z2 / (2 * trials)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / trials + z2 / (4 * trials * trials))
    return ConfidenceInterval(
        low=max(0.0, centre - half),
        high=min(1.0, centre + half),
        level=level,
        method="wilson",
    )


def newcombe_wilson_difference(
    treatment: BinomialSample,
    control: BinomialSample,
    *,
    level: float = 0.95,
) -> ConfidenceInterval | None:
    """Newcombe score interval for a difference of proportions (Wilson per arm)."""

    ti = wilson_interval(treatment.successes, treatment.trials, level=level)
    ci = wilson_interval(control.successes, control.trials, level=level)
    if ti is None or ci is None:
        return None
    assert treatment.rate is not None and control.rate is not None
    diff = treatment.rate - control.rate
    # Newcombe (1998) method 10: combine Wilson bounds asymmetrically.
    low = diff - math.sqrt((treatment.rate - ti.low) ** 2 + (ci.high - control.rate) ** 2)
    high = diff + math.sqrt((ti.high - treatment.rate) ** 2 + (control.rate - ci.low) ** 2)
    return ConfidenceInterval(low=low, high=high, level=level, method="newcombe_wilson")


def classify_lift(estimate: float | None, interval: ConfidenceInterval | None) -> LiftStatus:
    if estimate is None or interval is None:
        return "insufficient_data"
    if interval.low > 0:
        return "established_positive"
    if interval.high < 0:
        return "established_negative"
    return "not_established"


def causal_lift(
    treatment: BinomialSample,
    control: BinomialSample,
    *,
    task_class: str = "repo-chore",
    level: float = 0.95,
    snapshot_id: str | None = None,
    model_version: str | None = None,
    window: str | None = None,
) -> CausalLiftResult:
    """Compute treatment − control first-attempt success with status language (specs §19)."""

    if treatment.trials == 0 or control.trials == 0:
        return CausalLiftResult(
            task_class=task_class,
            treatment=treatment,
            control=control,
            estimate=None,
            interval=None,
            status="insufficient_data",
            snapshot_id=snapshot_id,
            model_version=model_version,
            window=window,
        )
    assert treatment.rate is not None and control.rate is not None
    estimate = treatment.rate - control.rate
    interval = newcombe_wilson_difference(treatment, control, level=level)
    status = classify_lift(estimate, interval)
    return CausalLiftResult(
        task_class=task_class,
        treatment=treatment,
        control=control,
        estimate=estimate,
        interval=interval,
        status=status,
        snapshot_id=snapshot_id,
        model_version=model_version,
        window=window,
    )


def brier_score(predictions: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Calibration error as Brier score of ``predicted_success`` (specs §23)."""

    if not predictions:
        raise ValueError("brier_score requires at least one observation")
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes must be the same length")
    total = 0.0
    for pred, outcome in zip(predictions, outcomes, strict=True):
        y = 1.0 if outcome else 0.0
        total += (pred - y) ** 2
    return total / len(predictions)


def rate(successes: int, trials: int) -> float | None:
    if trials == 0:
        return None
    return successes / trials


def mean(values: Iterable[float]) -> float | None:
    vals = list(values)
    if not vals:
        return None
    return sum(vals) / len(vals)
