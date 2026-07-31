"""``review``: apply promotion policy to a distilled draft (specs §4). M0 stub.

Unreachable on M0's default path (``distill`` always emits ``one_off`` — see ``distill.py``).
Kept as a real function, exercised directly by unit tests, so the registry is honest that all
fifteen nodes exist. The actual approve/reject choice is exogenous to ``RunState`` by design
(``contracts.graph``'s ``review`` routes both have an unconditional ``True`` predicate,
ADR-0008) — a real policy/human-queue lands with M3; M0's stand-in always approves.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def review(state: RunState, ctx: NodeContext) -> NodeOutcome:
    return NodeOutcome(state=state, route="approved", note="M0 stub policy: auto-approve (no queue yet)")
