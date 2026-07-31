"""``store``: write a new skill version and append to the ledger (specs §4, §21). M0 stub.

Unreachable on M0's default path (see ``distill.py``/``review.py``). No skill store exists yet
(M1), so this records only the ledger side of a hypothetical write — real transactional
skill-version writes land in M1.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def store(state: RunState, ctx: NodeContext) -> NodeOutcome:
    entry = ctx.ledger.append(
        actor=ctx.run_id,
        action="write",
        target=state.draft.get("skill_id", "unknown") if state.draft else "unknown",
        evidence={"run_id": ctx.run_id, "reusability": "reusable"},
        at=now(),
    )
    new_state = state.model_copy(
        update={"written_versions": [*state.written_versions, {"ledger_entry_seq": entry.seq}]}
    )
    return NodeOutcome(state=new_state, route="always", note=f"ledger entry seq={entry.seq}")
