"""Route completeness: the CI check that would have caught B3 and B6 (refactor-plan R3).

Every node MUST have at least one legal outgoing route for a state that actually reaches it,
and every FailureClass MUST have at least one producing source. This is what
`docs/implementation-plan.md`'s "Route completeness" R3 check literally is.
"""

from datetime import datetime, timezone

from contracts.branch import BranchState
from contracts.budget import Budget, Spend
from contracts.criteria import CriterionResult, TaskCriterion
from contracts.failure import FAILURE_CLASSES, FailureSignal, FailureVerdict
from contracts.graph import (
    NODES,
    TERMINAL_NODES,
    every_failure_class_has_a_producer,
    legal_routes,
    routes_from,
)
from contracts.run import RunManifest, RunState, Task

_NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _base_state(**overrides) -> RunState:
    defaults = dict(
        run_id="run-1",
        task=Task(task_id="task-1", request="do the thing", submitted_at=_NOW),
        manifest=RunManifest(criteria_hash="abc123"),
        criteria_locked_at=_NOW,
    )
    defaults.update(overrides)
    return RunState(**defaults)


def test_every_non_terminal_node_has_at_least_one_declared_route():
    for node in NODES:
        if node in TERMINAL_NODES or node == "finalize":
            continue
        assert routes_from(node), f"node {node!r} has no declared outgoing route at all"


def test_every_declared_failure_class_has_a_producer():
    producers = every_failure_class_has_a_producer()
    missing = [cls for cls, sources in producers.items() if not sources]
    assert not missing, f"FailureClass(es) with no producer edge: {missing}"
    assert set(producers) == set(FAILURE_CLASSES)


def test_single_attempt_pass_routes_directly_to_distill_with_no_join():
    """B3's acceptance criterion: a single-branch run has a fully specified path to distill."""

    criterion = TaskCriterion(id="tests", kind="command", run="pytest -q", source="caller")
    state = _base_state(
        criteria=[criterion],
        transcript_ref="sha256:abc",
        results=[CriterionResult(criterion_id="tests", passed=True)],
    )
    assert state.branches == []
    routes = legal_routes("validate", state)
    assert {r.target for r in routes} == {"distill"}
    assert not any(r.target == "join" for r in routes)


def test_single_attempt_failure_routes_to_classify_failure_not_join():
    criterion = TaskCriterion(id="tests", kind="command", run="pytest -q", source="caller")
    state = _base_state(
        criteria=[criterion],
        transcript_ref="sha256:abc",
        results=[CriterionResult(criterion_id="tests", passed=False)],
        failure_signal=FailureSignal(source="validator", detail="tests failed", at=_NOW),
    )
    routes = legal_routes("validate", state)
    assert {r.target for r in routes} == {"classify_failure"}


def test_solve_can_reach_classify_failure_before_any_result_exists():
    """environment/tool/budget failures occur before or instead of validation (B4)."""

    state = _base_state(failure_signal=FailureSignal(source="orchestrator", detail="setup failed", at=_NOW))
    assert state.results == []
    routes = legal_routes("solve", state)
    assert {r.target for r in routes} == {"classify_failure"}


def test_solve_failure_after_retry_routes_to_classify_not_stale_validation():
    """A retry keeps diagnostic results, but its pre-validation signal remains authoritative."""

    state = _base_state(
        transcript_ref="sha256:prior-attempt",
        results=[CriterionResult(criterion_id="tests", passed=False)],
        failure_signal=FailureSignal(source="solver", detail="budget exhausted", at=_NOW),
    )
    routes = legal_routes("solve", state)
    assert [route.predicate_name for route in routes] == ["pre_validation_failure_signal"]


def test_branched_run_routes_through_join():
    branch = BranchState(
        branch_id="b1",
        strategy="apply",
        workspace_ref="ws-1",
        budget=Budget(),
        status="succeeded",
    )
    state = _base_state(branches=[branch], transcript_ref="sha256:abc")
    routes = legal_routes("validate", state)
    assert {r.target for r in routes} == {"join"}


def test_classify_failure_routes_to_record_dead_end_on_budget_exhaustion():
    state = _base_state(
        spent=Spend(attempts=4),
        failure_signal=FailureSignal(source="validator", detail="tests failed", at=_NOW),
        failure=FailureVerdict(failure_class="execution", counts_against_trust=True),
    )
    routes = legal_routes("classify_failure", state)
    assert {r.target for r in routes} == {"record_dead_end"}


def test_classify_failure_never_routes_to_evolve_for_criteria_class():
    """A criteria failure class MUST route to record_dead_end (with human escalation), never evolve."""

    state = _base_state(
        failure_signal=FailureSignal(source="validator", detail="criteria contradictory", at=_NOW),
        failure=FailureVerdict(failure_class="criteria", counts_against_trust=False, escalate_to_human=True),
    )
    routes = legal_routes("classify_failure", state)
    assert {r.target for r in routes} == {"record_dead_end"}


def test_no_task_plane_route_reaches_a_skill_quarantine_action():
    """ADR-0008: quarantine_version is not a task-plane node; the graph must not expose it."""

    assert "quarantine" not in NODES
    assert "quarantine_version" not in NODES
    assert {"record_dead_end", "reject_draft"}.issubset(NODES)
