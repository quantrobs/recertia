"""``finalize``: set the run's terminal outcome (specs §4). The only node with no outgoing route.

Terminal is derived from which node routed here, per the annotations in specs §4.1:
``store``/``distill`` (one-off) -> ``solved``, ``record_dead_end`` -> ``unsolved``,
``reject_draft`` -> ``rejected``, ``plan`` (abstain) -> ``abstained``.
"""

from __future__ import annotations

from contracts.run import RunState
from recertia.nodes.context import NodeContext, NodeOutcome

_TERMINAL_BY_PREDECESSOR = {
    "plan": "abstained",
    "distill": "solved",
    "store": "solved",
    "record_dead_end": "unsolved",
    "reject_draft": "rejected",
}


def finalize(state: RunState, ctx: NodeContext) -> NodeOutcome:
    predecessor = state.route_log[-1].node if state.route_log else ""
    terminal = _TERMINAL_BY_PREDECESSOR.get(predecessor, "error")
    new_state = state.model_copy(update={"terminal": terminal})
    return NodeOutcome(state=new_state, route=None)
