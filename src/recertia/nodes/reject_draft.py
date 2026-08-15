"""``reject_draft``: record a rejected distillation with curation provenance."""

from __future__ import annotations

from contracts.run import RunState
from recertia.nodes._util import now
from recertia.nodes.context import NodeContext, NodeOutcome


def reject_draft(state: RunState, ctx: NodeContext) -> NodeOutcome:
    skill_id = (state.draft or {}).get("skill_id", "unknown")
    entry = ctx.ledger.append(
        actor=ctx.run_id,
        action="policy_change",
        target=str(skill_id),
        evidence={"run_id": ctx.run_id, "draft": bool(state.draft), "decision": "reject_draft"},
        at=now(),
    )
    return NodeOutcome(
        state=state,
        route="always",
        note=f"rejected draft {skill_id}; ledger seq={entry.seq}",
    )
