"""Unit tests for contribution / trust / retrieval-ablation estimates."""

from __future__ import annotations

import pytest

from contracts.eval import BinomialSample
from fandea.memory.procedural.contribution import (
    estimate_contribution,
    estimate_retrieval_ablation,
    trust_score,
)


def test_trust_score_smoothed_ratio() -> None:
    assert trust_score(applications=0, successes=0) == pytest.approx(0.5)
    assert trust_score(applications=8, successes=8) == pytest.approx(0.9)
    assert trust_score(applications=10, successes=0) == pytest.approx(1 / 12)


def test_estimate_contribution_positive_interval() -> None:
    contrib = estimate_contribution(
        shadow=BinomialSample(successes=80, trials=100),
        suppression=BinomialSample(successes=40, trials=100),
        has_required_non_judge=True,
    )
    assert contrib.applications == 100
    assert contrib.successes == 80
    assert contrib.suppressed_applications == 100
    assert contrib.estimate == pytest.approx(0.4)
    assert contrib.interval_low is not None and contrib.interval_high is not None
    assert contrib.interval_low > 0
    assert contrib.last_evaluated_at is not None


def test_estimate_contribution_skips_without_required_non_judge() -> None:
    contrib = estimate_contribution(
        shadow=BinomialSample(successes=80, trials=100),
        suppression=BinomialSample(successes=40, trials=100),
        has_required_non_judge=False,
    )
    assert contrib.interval_low is None
    assert contrib.interval_high is None
    assert contrib.estimate == pytest.approx(0.4)


def test_estimate_retrieval_ablation_records_class_effect() -> None:
    effect = estimate_retrieval_ablation(
        task_class="repo-chore",
        retrieval_enabled=BinomialSample(successes=70, trials=100),
        retrieval_suppressed=BinomialSample(successes=50, trials=100),
    )
    assert effect.task_class == "repo-chore"
    assert effect.retrieval_enabled == 100
    assert effect.retrieval_enabled_successes == 70
    assert effect.retrieval_suppressed == 100
    assert effect.estimate == pytest.approx(0.2)
    assert effect.interval_low is not None and effect.interval_high is not None
    assert effect.last_evaluated_at is not None
