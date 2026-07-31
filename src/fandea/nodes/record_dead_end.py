"""``record_dead_end``: record a failed run's outcome (specs §4, ADR-0008). M0 stub.

No episodic store exists yet (M2); M0 records the dead end onto the run state itself (via a
route-log note) so the done-when — "a run whose criteria always fail terminates here with a
failure class rather than looping" — is directly observable without a memory plane to query.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def record_dead_end(state: RunState, ctx: NodeContext) -> NodeOutcome:
    failure_class = state.failure.failure_class if state.failure else "unknown"
    return NodeOutcome(
        state=state,
        route="always",
        note=f"dead end recorded: failure_class={failure_class!r} (M0 stub: episodic store lands in M2)",
    )
