"""``fan_out``: split budget and materialise portfolio/decomposition branches (M6)."""

from __future__ import annotations

from contracts.branch import BranchState
from contracts.budget import Budget
from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def fan_out(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if state.strategy not in ("portfolio", "decomposition"):
        return NodeOutcome(state=state, route="always", note="no fan-out strategy")

    parent = state.budget
    n = max(2, len(state.bundle.skills) if state.strategy == "portfolio" else 2)
    # Equal budget division; leftover stays with parent accounting via spent checks later.
    child_budget = Budget(
        max_attempts=max(1, parent.max_attempts // n),
        max_tokens=parent.max_tokens // n if parent.max_tokens else None,
        max_cost_usd=(parent.max_cost_usd / n) if parent.max_cost_usd else None,
        max_wall_clock_s=parent.max_wall_clock_s,
        max_tool_calls=max(1, parent.max_tool_calls // n),
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
                    workspace_ref=f"{ctx.workdir}/branch-p{i}",
                    budget=child_budget,
                    status="dispatched",
                )
            )
    else:
        # Decomposition: require criteria partitionability.
        owned = _partition_criteria(state)
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
                    workspace_ref=f"{ctx.workdir}/branch-d{i}",
                    budget=child_budget,
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

    new_state = state.model_copy(update={"branches": branches})
    return NodeOutcome(
        state=new_state,
        route="always",
        note=f"dispatched {len(branches)} {state.strategy} branches",
    )


def _partition_criteria(state: RunState) -> list[tuple[str, list[str]]] | None:
    """Return subtask partitions or None when criteria cannot be cleanly split."""

    crits = list(state.criteria)
    if len(crits) < 2:
        return None
    # Simple even split; refuse if any criterion lacks an id (impossible) or odd join-only flag.
    if any(getattr(c, "kind", None) == "judge" and c.weight >= 1.0 for c in crits):
        # Required judges stay at join — still partitionable if ≥2 non-join criteria.
        pass
    mid = len(crits) // 2
    if mid == 0 or mid == len(crits):
        return None
    left = crits[:mid]
    right = crits[mid:]
    return [
        ("part-a", [c.id for c in left]),
        ("part-b", [c.id for c in right]),
    ]
