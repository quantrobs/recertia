"""``join``: audit and reduce fan-out branches (specs §4, §5.3, ADR-0008). No-op stub in M0.

Only reached when ``fan_out`` produced branches; ``plan`` never returns ``portfolio`` or
``decomposition`` in M0 (see ``plan.py``), so this node is unreachable on the default path.
Kept as a real (if minimal) implementation — not a bare pass-through — so the fifteen-node
registry is honest about what exists versus what is deferred to M6.
"""

from __future__ import annotations

from contracts.branch import MergeAudit
from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def join(state: RunState, ctx: NodeContext) -> NodeOutcome:
    expected = len(state.branches)
    received = sum(1 for b in state.branches if b.status in ("succeeded", "failed"))
    missing = [b.branch_id for b in state.branches if b.status not in ("succeeded", "failed")]
    audit = MergeAudit(
        merge_id=f"{ctx.run_id}-join-{len(state.merge_audits)}",
        expected=expected,
        received=received,
        missing=missing,
        action="proceeded" if not missing else "flagged",
    )
    new_state = state.model_copy(update={"merge_audits": [*state.merge_audits, audit]})
    route = "merge_complete_and_passing" if audit.is_complete else "otherwise"
    return NodeOutcome(state=new_state, route=route, note="M0 stub: real portfolio/decomposition in M6")
