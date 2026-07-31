"""``reject_draft``: record a review rejection (specs §4, ADR-0008). M0 stub.

Unreachable on M0's default path (``review`` always approves — see ``review.py``). No
Correction Miner exists yet (M7) to consume the rejection diff; recorded as a note only.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def reject_draft(state: RunState, ctx: NodeContext) -> NodeOutcome:
    return NodeOutcome(state=state, route="always", note="draft rejected (M0 stub: no Correction Miner yet)")
