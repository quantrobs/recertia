from __future__ import annotations

from datetime import datetime, timezone

from contracts.branch import BranchState
from contracts.budget import Budget
from contracts.criteria import TaskCriterion
from contracts.run import RunState, Task
from recertia.nodes.fan_out import fan_out
from recertia.nodes.join import join


def _task() -> Task:
    return Task(task_id="t", request="DECOMPOSE: assemble output", submitted_at=datetime.now(timezone.utc))


def test_fan_out_refuses_unreservable_branch_attempts(ctx) -> None:
    state = RunState(
        run_id=ctx.run_id,
        task=_task(),
        criteria=[
            TaskCriterion(id="one", kind="assertion", expr="True", source="caller"),
            TaskCriterion(id="two", kind="assertion", expr="True", source="caller"),
        ],
        strategy="decomposition",
        budget=Budget(max_attempts=1),
    )

    outcome = fan_out(state, ctx)

    assert outcome.state.failure_signal is not None
    assert "attempts" in outcome.state.failure_signal.detail
    assert not outcome.state.branches


def test_decomposition_layered_fan_in_materializes_and_scores_parent(ctx) -> None:
    criteria: list[TaskCriterion] = []
    branches: list[BranchState] = []
    for index in range(8):
        name = f"part-{index}.txt"
        criteria.append(
            TaskCriterion(
                id=f"c{index}",
                kind="assertion",
                expr=f"(workdir / '{name}').read_text() == '{index}'",
                source="caller",
            )
        )
        branch_dir = ctx.workdir / f"branch-{index}"
        branch_dir.mkdir()
        (branch_dir / name).write_text(str(index), encoding="utf-8")
        branches.append(
            BranchState(
                branch_id=f"b{index}",
                kind="decomposition",
                strategy="scratch",
                workspace_ref=str(branch_dir),
                budget=Budget(),
                status="succeeded",
                owned_criteria=[f"c{index}"],
            )
        )
    state = RunState(
        run_id=ctx.run_id,
        task=_task(),
        criteria=criteria,
        strategy="decomposition",
        branches=branches,
    )

    outcome = join(state, ctx)

    assert outcome.route == "merge_complete_and_passing"
    assert all(result.passed for result in outcome.state.results)
    assert (ctx.workdir / "part-7.txt").read_text(encoding="utf-8") == "7"
    audit = outcome.state.merge_audits[-1]
    assert audit.layered
    assert len(audit.batches) > 1
    assert outcome.state.artifacts[-1].description == "materialized decomposition output"
