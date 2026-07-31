"""``plan``: choose a strategy (specs §4). M0 stub: always ``scratch``.

Fan-out (``portfolio``/``decomposition``) and skill ``apply``/``adapt`` both require memory
that does not exist until M1/M6; ``abstain`` requires a calibrated model this milestone has no
model calls to calibrate. ``scratch`` is therefore the only honest choice in M0 — it is not a
placeholder pretending otherwise, it is the correct answer when the memory bundle is empty.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def plan(state: RunState, ctx: NodeContext) -> NodeOutcome:
    new_state = state.model_copy(
        update={
            "strategy": "scratch",
            "strategy_reason": "M0 stub: memory bundle empty, no fan-out until M6; solve from scratch.",
        }
    )
    return NodeOutcome(state=new_state, route="single_strategy")
