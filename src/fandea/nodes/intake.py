"""``intake``: normalise the request, lock criteria, record the manifest (specs §4, §15.1)."""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes._util import criteria_hash, now
from fandea.nodes.context import NodeContext, NodeOutcome


def intake(state: RunState, ctx: NodeContext) -> NodeOutcome:
    """Lock the ``TaskCriterion`` set and record its hash in the manifest.

    Every other field ``intake`` might set (model/tool fingerprints, index snapshot id) comes
    from memory/retrieval services that do not exist yet in M0; those stay ``None`` on the
    manifest until M1+ fills them in.
    """

    manifest = state.manifest.model_copy(update={"criteria_hash": criteria_hash(state.criteria)})
    new_state = state.model_copy(update={"manifest": manifest, "criteria_locked_at": now()})
    return NodeOutcome(state=new_state, route="always")
