"""``fan_out``: split budget across branches (specs §4, §5.3). Unreachable in M0.

``plan`` never returns ``portfolio``/``decomposition`` in M0 (see ``plan.py``), so this is a
true no-op stub kept only so the fifteen-node registry is complete and the route-completeness
check has a callable to point at. Real fan-out lands in M6.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def fan_out(state: RunState, ctx: NodeContext) -> NodeOutcome:
    return NodeOutcome(state=state, route="always", note="M0 stub: fan-out lands in M6")
