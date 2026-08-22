"""Faithfulness harness: intervene on condensed memory and score trajectory + lift.

Eval-only T3. Production retrieve/store are not imported. Nodes and jobs must not
import this module (ADR-0005).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from contracts.eval import BinomialSample
from contracts.faithfulness import (
    FAITHFULNESS_STRATEGY_PREFIX,
    FaithfulnessArmResult,
    FaithfulnessIntervention,
    FaithfulnessReport,
    TrajectoryDivergence,
)
from contracts.skill import SkillVersion
from recertia.evals.interventions import apply_intervention
from recertia.evals.statistics import causal_lift

_DEFAULT_INTERVENTIONS: tuple[FaithfulnessIntervention, ...] = (
    "empty",
    "corrupt",
    "irrelevant",
    "filler",
)


def strategy_tag(intervention: FaithfulnessIntervention) -> str:
    return f"{FAITHFULNESS_STRATEGY_PREFIX}{intervention}"


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    left, right = set(a), set(b)
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def edit_distance(a: Sequence[str], b: Sequence[str]) -> int:
    """Levenshtein distance over event-kind sequences."""

    if a == b:
        return 0
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def trajectory_divergence(
    baseline: Sequence[str], intervened: Sequence[str]
) -> TrajectoryDivergence:
    return TrajectoryDivergence(
        jaccard=jaccard(baseline, intervened),
        edit_distance=edit_distance(baseline, intervened),
        event_count_baseline=len(baseline),
        event_count_intervened=len(intervened),
    )


def detectable_change(
    *,
    lift_status: str | None,
    divergence: TrajectoryDivergence,
    jaccard_drop: float = 0.15,
    min_edit_distance: int = 1,
) -> bool:
    if lift_status in {"established_positive", "established_negative"}:
        return True
    if divergence.jaccard <= 1.0 - jaccard_drop:
        return True
    return divergence.edit_distance >= min_edit_distance


def evaluate_faithfulness(
    *,
    skill: SkillVersion,
    baseline: BinomialSample,
    baseline_events: Sequence[str],
    outcomes: dict[FaithfulnessIntervention, BinomialSample],
    events: dict[FaithfulnessIntervention, Sequence[str]],
    donor: SkillVersion | None = None,
    skill_used: bool = True,
    snapshot_id: str | None = None,
    min_independent_runs: int = 5,
) -> FaithfulnessReport:
    """Score interventions from already-collected success vectors and event streams.

    Does not run the solver. Callers that execute tasks must tag those observations
    with :func:`strategy_tag` and ``is_eval_fixture=True``.
    """

    arms: list[FaithfulnessArmResult] = []
    for intervention in _DEFAULT_INTERVENTIONS:
        if intervention not in outcomes:
            continue
        if intervention == "irrelevant":
            apply_intervention(skill, intervention, donor=donor)
        else:
            apply_intervention(skill, intervention)
        sample = outcomes[intervention]
        intervened_events = list(events.get(intervention, []))
        divergence = trajectory_divergence(baseline_events, intervened_events)
        lift = causal_lift(
            baseline,
            sample,
            task_class=skill.task_class,
            snapshot_id=snapshot_id,
            min_independent_runs=min_independent_runs,
        )
        delta = None
        if baseline.rate is not None and sample.rate is not None:
            delta = sample.rate - baseline.rate
        changed = detectable_change(lift_status=lift.status, divergence=divergence)
        if not skill_used:
            changed = False
        arms.append(
            FaithfulnessArmResult(
                intervention=intervention,
                strategy=strategy_tag(intervention),
                performance_delta=delta,
                lift=lift,
                divergence=divergence,
                detectable_change=changed,
                skill_used=skill_used,
            )
        )
    score = (sum(1 for arm in arms if arm.detectable_change) / len(arms)) if arms else 0.0
    return FaithfulnessReport(
        skill_id=skill.skill_id,
        version=skill.version,
        task_class=skill.task_class,
        snapshot_id=snapshot_id,
        score=score,
        arms=arms,
        baseline_successes=baseline.successes,
        baseline_trials=baseline.trials,
        at=datetime.now(timezone.utc),
    )
