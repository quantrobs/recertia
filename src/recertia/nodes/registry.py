"""Maps each of the fifteen node names to its implementation (specs §4, ADR-0008)."""

from __future__ import annotations

from typing import Callable

from contracts.run import RunState
from recertia.nodes.classify_failure import classify_failure
from recertia.nodes.context import NodeContext, NodeOutcome
from recertia.nodes.distill import distill
from recertia.nodes.evolve import evolve
from recertia.nodes.fan_out import fan_out
from recertia.nodes.finalize import finalize
from recertia.nodes.intake import intake
from recertia.nodes.join import join
from recertia.nodes.plan import plan
from recertia.nodes.record_dead_end import record_dead_end
from recertia.nodes.reject_draft import reject_draft
from recertia.nodes.retrieve import retrieve
from recertia.nodes.review import review
from recertia.nodes.solve import solve
from recertia.nodes.store import store
from recertia.nodes.validate import validate

NodeFunc = Callable[[RunState, NodeContext], NodeOutcome]

NODE_FUNCS: dict[str, NodeFunc] = {
    "intake": intake,
    "retrieve": retrieve,
    "plan": plan,
    "fan_out": fan_out,
    "solve": solve,
    "validate": validate,
    "join": join,
    "classify_failure": classify_failure,
    "evolve": evolve,
    "distill": distill,
    "review": review,
    "store": store,
    "record_dead_end": record_dead_end,
    "reject_draft": reject_draft,
    "finalize": finalize,
}
