"""Maps each of the fifteen node names to its implementation (specs §4, ADR-0008)."""

from __future__ import annotations

from typing import Callable

from contracts.run import RunState
from fandea.nodes.classify_failure import classify_failure
from fandea.nodes.context import NodeContext, NodeOutcome
from fandea.nodes.distill import distill
from fandea.nodes.evolve import evolve
from fandea.nodes.fan_out import fan_out
from fandea.nodes.finalize import finalize
from fandea.nodes.intake import intake
from fandea.nodes.join import join
from fandea.nodes.plan import plan
from fandea.nodes.record_dead_end import record_dead_end
from fandea.nodes.reject_draft import reject_draft
from fandea.nodes.retrieve import retrieve
from fandea.nodes.review import review
from fandea.nodes.solve import solve
from fandea.nodes.store import store
from fandea.nodes.validate import validate

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
