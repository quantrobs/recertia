"""M4 unit tests: Wilson / causal_lift / calibration / ablation."""

from __future__ import annotations

import pytest

from contracts.eval import BinomialSample
from fandea.evals.ablation import assign_arm
from fandea.evals.statistics import brier_score, causal_lift, wilson_interval


def test_injected_lift_excludes_zero() -> None:
    result = causal_lift(
        BinomialSample(successes=80, trials=100),
        BinomialSample(successes=50, trials=100),
        task_class="repo-chore",
    )
    assert result.estimate == pytest.approx(0.30)
    assert result.interval is not None
    assert result.interval.low > 0
    assert result.status == "established_positive"
    assert result.render_status() == "established positive"
    # Pin the Newcombe/Wilson construction numerically (method stability).
    assert result.interval.low == pytest.approx(0.169084, abs=1e-5)
    assert result.interval.high == pytest.approx(0.416997, abs=1e-5)


def test_null_effect_reports_not_established() -> None:
    result = causal_lift(
        BinomialSample(successes=50, trials=100),
        BinomialSample(successes=50, trials=100),
        task_class="repo-chore",
    )
    assert result.estimate == pytest.approx(0.0)
    assert result.interval is not None
    assert result.interval.low <= 0 <= result.interval.high
    assert result.status == "not_established"
    assert result.render_status() == "not established"


def test_zero_sample_arm_is_insufficient_data() -> None:
    result = causal_lift(
        BinomialSample(successes=10, trials=20),
        BinomialSample(successes=0, trials=0),
    )
    assert result.estimate is None
    assert result.status == "insufficient_data"


def test_wilson_interval_bounds() -> None:
    interval = wilson_interval(50, 100)
    assert interval is not None
    assert 0 <= interval.low < 0.5 < interval.high <= 1


def test_brier_score_perfect_and_worst() -> None:
    assert brier_score([1.0, 0.0], [True, False]) == pytest.approx(0.0)
    assert brier_score([0.0, 1.0], [True, False]) == pytest.approx(1.0)


def test_ablation_exclusions_and_determinism() -> None:
    excluded = assign_arm(run_id="r1", task_class="repo-chore", is_eval_fixture=True)
    assert excluded.eligible is False
    assert excluded.arm == "treatment"

    a = assign_arm(run_id="same", task_class="repo-chore", seed=7, rate=0.5)
    b = assign_arm(run_id="same", task_class="repo-chore", seed=7, rate=0.5)
    assert a.arm == b.arm
    assert a.reason == b.reason
