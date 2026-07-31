"""``fan_out``: split budget and materialise portfolio/decomposition branches (M6)."""

from __future__ import annotations

from contracts.branch import BranchState
from contracts.budget import Budget, BudgetReservation, budget_excess
from contracts.failure import FailureSignal
from contracts.run import RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def fan_out(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if state.strategy not in ("portfolio", "decomposition"):
        return NodeOutcome(state=state, route="always", note="no fan-out strategy")

    parent = state.budget
    desired = (
        len(state.bundle.skills)
        if state.strategy == "portfolio"
        else min(len(state.criteria), state.budget.max_branches)
    )
    n = min(state.budget.max_branches, max(2, desired))
    # A branch gets a real lease, not merely a copy of the parent limit. Every finite
    # dimension is divided before dispatch so concurrent workers cannot oversubscribe it.
    child_budget = Budget(
        max_attempts=max(1, parent.max_attempts // n),
        max_tokens=parent.max_tokens // n if parent.max_tokens is not None else None,
        max_cost_usd=(parent.max_cost_usd / n) if parent.max_cost_usd is not None else None,
        max_wall_clock_s=max(1, parent.max_wall_clock_s // n),
        max_tool_calls=max(1, parent.max_tool_calls // n),
        max_branches=1,
        max_parallel_steps=parent.max_parallel_steps,
        claim_timeout_s=parent.claim_timeout_s,
        max_versions_written=parent.max_versions_written,
    )
    requested_per_branch = BudgetReservation(
        attempts=1,
        tool_calls=len(ctx.script or ["true"]),
        tokens=child_budget.max_tokens or 0,
        wall_clock_s=min(60, child_budget.max_wall_clock_s),
        cost_usd=0.01 * (1 + len(ctx.script or ["true"])),
    )
    requested = BudgetReservation(
        attempts=requested_per_branch.attempts * n,
        tool_calls=requested_per_branch.tool_calls * n,
        tokens=requested_per_branch.tokens * n,
        wall_clock_s=requested_per_branch.wall_clock_s * n,
        cost_usd=requested_per_branch.cost_usd * n,
    )
    exhausted = budget_excess(parent, state.spent, state.reserved, requested)
    if exhausted is not None:
        return NodeOutcome(
            state=state.model_copy(
                update={
                    "failure_signal": FailureSignal(
                        source="orchestrator",
                        detail=f"budget exhausted before fan-out reservation: {exhausted}",
                        at=now(),
                    )
                }
            ),
            route="pre_dispatch_budget_failure",
            note=f"fan-out refused: {exhausted} budget cannot reserve {n} branches",
        )

    branches: list[BranchState] = []
    if state.strategy == "portfolio":
        # Competing strategies: top skills + scratch.
        candidates = list(state.bundle.skills[: n - 1])
        strategies = [("apply", c) for c in candidates] + [("scratch", None)]
        for i, (strat, cand) in enumerate(strategies):
            branches.append(
                BranchState(
                    branch_id=f"{ctx.run_id}-p{i}",
                    kind="portfolio",
                    strategy=strat,  # type: ignore[arg-type]
                    candidate=cand.model_dump(mode="json") if cand else None,
                    workspace_ref=str(ctx.workdir / f"{ctx.run_id}-p{i}"),
                    budget=child_budget,
                    reserved=requested_per_branch,
                    status="dispatched",
                )
            )
    else:
        # Decomposition: require criteria partitionability.
        owned = _partition_criteria(state, max_parts=n)
        if owned is None:
            # Should have been refused at plan; degrade safely.
            return NodeOutcome(
                state=state.model_copy(update={"strategy": "scratch", "branches": []}),
                route="always",
                note="decomposition refused: criteria not partitionable",
            )
        for i, (subtask, crit_ids) in enumerate(owned):
            branches.append(
                BranchState(
                    branch_id=f"{ctx.run_id}-d{i}",
                    kind="decomposition",
                    strategy="scratch",
                    subtask=subtask,
                    workspace_ref=str(ctx.workdir / f"{ctx.run_id}-d{i}"),
                    budget=child_budget,
                    reserved=requested_per_branch,
                    status="dispatched",
                    owned_criteria=crit_ids,
                )
            )

    # Materialise disjoint workspace clones.
    for branch in branches:
        path = ctx.workdir / branch.branch_id
        path.mkdir(parents=True, exist_ok=True)
        # Clone current workdir files into the branch workspace.
        for item in ctx.workdir.iterdir():
            if item.name.startswith(ctx.run_id) or item.name.startswith("branch-"):
                continue
            dest = path / item.name
            if item.is_file() and not dest.exists():
                dest.write_bytes(item.read_bytes())

    new_state = state.model_copy(
        update={
            "branches": branches,
            "reserved": BudgetReservation(
                attempts=state.reserved.attempts + requested.attempts,
                tool_calls=state.reserved.tool_calls + requested.tool_calls,
                tokens=state.reserved.tokens + requested.tokens,
                wall_clock_s=state.reserved.wall_clock_s + requested.wall_clock_s,
                cost_usd=state.reserved.cost_usd + requested.cost_usd,
            ),
        }
    )
    return NodeOutcome(
        state=new_state,
        route="always",
        note=f"dispatched {len(branches)} {state.strategy} branches",
    )


def _partition_criteria(
    state: RunState, *, max_parts: int | None = None
) -> list[tuple[str, list[str]]] | None:
    """Return subtask partitions or None when criteria cannot be cleanly split."""

    crits = list(state.criteria)
    if len(crits) < 2:
        return None
    # Simple even split; refuse if any criterion lacks an id (impossible) or odd join-only flag.
    if any(getattr(c, "kind", None) == "judge" and c.weight >= 1.0 for c in crits):
        # Required judges stay at join — still partitionable if ≥2 non-join criteria.
        pass
    part_count = min(max_parts or 2, len(crits))
    if part_count < 2:
        return None
    parts = [[] for _ in range(part_count)]
    for index, criterion in enumerate(crits):
        parts[index % part_count].append(criterion)
    return [
        (f"part-{index + 1}", [criterion.id for criterion in part])
        for index, part in enumerate(parts)
        if part
    ]
