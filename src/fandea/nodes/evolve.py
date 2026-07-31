"""``evolve``: restore the workspace and re-dispatch to ``solve`` (specs §4, §16). M0 stub.

M0 has no repair-move differentiation (that is M2's job, per the failure taxonomy in specs
§16) — every class that reaches ``evolve`` gets the same move: restore the workspace to the
run's original clean snapshot and retry the identical script. What stops this from looping
forever on a genuinely unsatisfiable task is not ``evolve`` itself; it is the route table's own
budget and no-progress checks (``contracts.graph._budget_remains_with_progress``), which is
exactly the point — ``evolve`` "decrements a budget" by incrementing ``spent.attempts`` inside
``solve`` on the next pass, and the orchestrator never calls ``evolve`` at all once that check
fails.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def evolve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    clean_ref = state.workspace_snapshots[0].snapshot_ref
    ctx.workspaces.restore(ctx.workdir, clean_ref)

    snapshots = list(state.workspace_snapshots)
    snapshots[0] = snapshots[0].model_copy(update={"restored": True})

    new_state = state.model_copy(update={"workspace_snapshots": snapshots})
    return NodeOutcome(state=new_state, route="always", note=f"restored workspace from {clean_ref!r}")
