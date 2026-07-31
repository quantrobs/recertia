"""``retrieve``: federated memory query (specs §4, §5.5). M0 stub: memory does not exist yet.

Every retrieve in M0 returns an empty, unsuppressed bundle — the honest "a competent agent
with no memory" baseline the architecture commits to degrading no worse than
(``docs/architecture.md`` design goals). Real retrieval lands in M1.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def retrieve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    return NodeOutcome(state=state, route="always", note="M0 stub: memory does not exist yet")
