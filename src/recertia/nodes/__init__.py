"""The fifteen task-plane nodes (specs §4) and their injected ``NodeContext``.

``NODE_FUNCS`` is the registry the graph engine dispatches through. Route legality is
owned by ``contracts.graph`` (ADR-0008); nodes return a ``NodeOutcome`` with a predicate
name that must be among the legal routes for the current ``RunState``.
"""

from recertia.nodes.context import NodeContext, NodeOutcome
from recertia.nodes.registry import NODE_FUNCS

__all__ = ["NodeContext", "NodeOutcome", "NODE_FUNCS"]
