"""The task-plane route table, as data (ADR-0008; refactor-plan B3, B4).

This is the executable form of ``specifications.md`` §4.1. It exists so "route completeness"
is a test (``tests/contracts/test_route_completeness.py``), not a claim: every node has at
least one legal outgoing route for every reachable predicate state, and every ``FailureClass``
has at least one producing edge into ``classify_failure``.

Fifteen nodes. ``quarantine`` (overloaded across three meanings) is removed; ``record_dead_end``
and ``reject_draft`` take its task-plane share. The third meaning — marking a *stored skill
version* harmful — is not a task-plane decision at all (ADR-0008) and does not appear here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from contracts.failure import FAILURE_CLASSES
from contracts.run import RunState

NODES: tuple[str, ...] = (
    "intake",
    "retrieve",
    "plan",
    "fan_out",
    "solve",
    "validate",
    "join",
    "classify_failure",
    "evolve",
    "distill",
    "review",
    "store",
    "record_dead_end",
    "reject_draft",
    "finalize",
)

TERMINAL_NODES: frozenset[str] = frozenset({"store", "record_dead_end", "reject_draft"})


@dataclass(frozen=True)
class Route:
    source: str
    target: str
    predicate_name: str
    predicate: Callable[[RunState], bool]
    description: str


def _required_criteria_pass(state: RunState) -> bool:
    required_ids = {c.id for c in state.criteria if c.is_required}
    if not required_ids:
        return True
    passed = {r.criterion_id for r in state.results if r.passed}
    return required_ids.issubset(passed)


def _has_branches(state: RunState) -> bool:
    return len(state.branches) > 0


def _join_complete_and_passing(state: RunState) -> bool:
    if not state.merge_audits:
        return False
    if not all(m.is_complete for m in state.merge_audits):
        return False
    return _required_criteria_pass(state)


def _failure_signal_present(state: RunState) -> bool:
    return state.failure_signal is not None


def _budget_remains_with_progress(state: RunState) -> bool:
    if state.failure is None:
        return False
    if state.failure.failure_class in ("criteria", "budget"):
        return False
    if state.spent.attempts >= state.budget.max_attempts:
        return False
    if len(state.results_history) >= 2 and state.results_history[-1] == state.results_history[-2]:
        return False
    return True


ROUTES: tuple[Route, ...] = (
    Route("intake", "retrieve", "always", lambda s: True, "Every intake proceeds to retrieve."),
    Route("retrieve", "plan", "always", lambda s: True, "Every retrieve proceeds to plan."),
    Route(
        "plan",
        "finalize",
        "abstain",
        lambda s: s.strategy == "abstain",
        "Abstention is a legitimate terminal outcome (terminal='abstained').",
    ),
    Route(
        "plan",
        "fan_out",
        "fan_out_strategy",
        lambda s: s.strategy in ("portfolio", "decomposition"),
        "Portfolio and decomposition strategies fan out before solving.",
    ),
    Route(
        "plan",
        "solve",
        "single_strategy",
        lambda s: s.strategy in ("apply", "adapt", "scratch"),
        "Single-strategy runs solve directly.",
    ),
    Route("fan_out", "solve", "always", lambda s: True, "Every branch is dispatched to solve."),
    Route(
        "solve",
        "classify_failure",
        "pre_validation_failure_signal",
        lambda s: s.failure_signal is not None and not s.results,
        (
            "Environment, tool, or mid-attempt budget failures occur before or instead of "
            "validation (ADR-0008); classify_failure never requires a result vector for these."
        ),
    ),
    Route(
        "solve",
        "validate",
        "attempt_completed",
        lambda s: s.transcript_ref is not None,
        "A completed attempt (whether it will pass or fail) proceeds to validation.",
    ),
    Route(
        "validate",
        "join",
        "has_branches",
        _has_branches,
        "join exists only when fan_out produced branches (ADR-0008 Option 1).",
    ),
    Route(
        "validate",
        "distill",
        "no_branches_and_passing",
        lambda s: not _has_branches(s) and _required_criteria_pass(s) and s.failure_signal is None,
        "Ordinary single-attempt runs route directly to distill on the default path.",
    ),
    Route(
        "validate",
        "classify_failure",
        "no_branches_and_failing",
        lambda s: not _has_branches(s) and (not _required_criteria_pass(s) or _failure_signal_present(s)),
        "A failed required criterion, or a raised FailureSignal, routes to classification.",
    ),
    Route(
        "join",
        "distill",
        "merge_complete_and_passing",
        _join_complete_and_passing,
        "Merge audits complete and the selected/synthesised result passes required criteria.",
    ),
    Route(
        "join",
        "classify_failure",
        "otherwise",
        lambda s: not _join_complete_and_passing(s),
        "A merge gap or a failed post-merge criterion routes to classification.",
    ),
    Route(
        "classify_failure",
        "evolve",
        "retry",
        _budget_remains_with_progress,
        "Budget remains, progress was observed, and the class is not criteria or budget.",
    ),
    Route(
        "classify_failure",
        "record_dead_end",
        "otherwise",
        lambda s: not _budget_remains_with_progress(s),
        "Exhausted budget, no progress, or a criteria/budget class ends the run here.",
    ),
    Route("evolve", "solve", "always", lambda s: True, "Evolve always re-dispatches to solve."),
    Route(
        "distill",
        "review",
        "reusable",
        lambda s: s.reusability is not None and s.reusability.verdict == "reusable",
        "A reusable draft goes to review.",
    ),
    Route(
        "distill",
        "finalize",
        "one_off",
        lambda s: s.reusability is not None and s.reusability.verdict == "one_off",
        "A one-off is recorded as evidence but not reviewed for storage.",
    ),
    Route(
        "review",
        "store",
        "approved",
        lambda s: True,  # decision is exogenous (human/policy); modelled at the orchestrator layer
        "Policy auto-approves or a human approved.",
    ),
    Route(
        "review",
        "reject_draft",
        "rejected",
        lambda s: True,  # mutually exclusive with 'approved' at the orchestrator layer
        "A human or policy rejected the draft.",
    ),
    Route("store", "finalize", "always", lambda s: True, "Store always finalises."),
    Route("record_dead_end", "finalize", "always", lambda s: True, "record_dead_end always finalises."),
    Route("reject_draft", "finalize", "always", lambda s: True, "reject_draft always finalises."),
)


def routes_from(node: str) -> tuple[Route, ...]:
    return tuple(r for r in ROUTES if r.source == node)


def legal_routes(node: str, state: RunState) -> list[Route]:
    """Every route out of ``node`` whose predicate holds for ``state``."""

    return [r for r in routes_from(node) if r.predicate(state)]


def producers_of(failure_class: str) -> tuple[str, ...]:
    """Which nodes can raise a signal that eventually classifies to this class.

    This is deliberately coarse (source-of-signal, not class), since the class itself is
    assigned by ``classify_failure`` reading evidence (affordance matches, criterion ids,
    merge audits), not by the route predicate. It exists so the exhaustiveness test can assert
    every class in ``FAILURE_CLASSES`` is reachable from at least one signal source.
    """

    sources_by_class: dict[str, tuple[str, ...]] = {
        "environment": ("solver", "orchestrator"),
        "tool": ("solver",),
        "retrieval": ("validator",),
        "plan": ("validator",),
        "execution": ("validator",),
        "criteria": ("validator",),
        "budget": ("orchestrator",),
        "merge": ("join",),
    }
    return sources_by_class.get(failure_class, ())


def every_failure_class_has_a_producer() -> dict[str, tuple[str, ...]]:
    """Maps every declared ``FailureClass`` to its producer sources; empty tuple means a gap."""

    return {cls: producers_of(cls) for cls in FAILURE_CLASSES}
