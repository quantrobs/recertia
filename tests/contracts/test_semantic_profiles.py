"""Semantic profiles catch what a structural schema cannot (ADR-0009, B5)."""

from datetime import datetime, timezone

from contracts.branch import BranchState
from contracts.budget import Budget
from contracts.criteria import TaskCriterion
from contracts.profiles import validate_checkpointed_run
from contracts.run import RunManifest, RunState, Task

_NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _task() -> Task:
    return Task(task_id="t1", request="do it", submitted_at=_NOW)


def test_checkpointed_run_with_criteria_but_no_lock_timestamp_is_flagged():
    state = RunState(
        run_id="r1",
        task=_task(),
        manifest=RunManifest(),
        criteria=[TaskCriterion(id="c1", kind="command", run="pytest -q", source="caller")],
        criteria_locked_at=None,
    )
    violations = validate_checkpointed_run(state)
    assert any("criteria_locked_at" in v for v in violations)


def test_checkpointed_run_with_lock_but_no_manifest_hash_is_flagged():
    state = RunState(
        run_id="r1",
        task=_task(),
        manifest=RunManifest(criteria_hash=None),
        criteria_locked_at=_NOW,
    )
    violations = validate_checkpointed_run(state)
    assert any("criteria_hash" in v for v in violations)


def test_a_properly_locked_run_has_no_violations():
    state = RunState(
        run_id="r1",
        task=_task(),
        manifest=RunManifest(criteria_hash="sha256:abc"),
        criteria_locked_at=_NOW,
        criteria=[TaskCriterion(id="c1", kind="command", run="pytest -q", source="caller")],
    )
    assert validate_checkpointed_run(state) == []


def test_a_branch_budget_exceeding_the_parent_is_flagged():
    oversized = Budget(max_wall_clock_s=99999)
    branch = BranchState(branch_id="b1", strategy="apply", workspace_ref="ws-1", budget=oversized)
    state = RunState(
        run_id="r1",
        task=_task(),
        manifest=RunManifest(),
        branches=[branch],
    )
    violations = validate_checkpointed_run(state)
    assert any("exceeds the parent budget" in v for v in violations)


def test_control_arm_without_suppression_is_flagged():
    # An empty-but-unmarked bundle does not trip RunState's own constructor validator (which
    # only guards non-empty bundles), so this is exactly what the semantic profile is for.
    state = RunState(run_id="r1", task=_task(), manifest=RunManifest(), arm="control")
    assert state.bundle.suppressed is False
    violations = validate_checkpointed_run(state)
    assert any("suppress" in v for v in violations)
