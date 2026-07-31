"""``intake``: normalise the request, lock criteria (critic if empty), record the manifest."""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes._util import criteria_hash, now
from fandea.nodes.context import NodeContext, NodeOutcome
from fandea.validation.critic import propose_criteria


def intake(state: RunState, ctx: NodeContext) -> NodeOutcome:
    """Lock the ``TaskCriterion`` set and record its hash in the manifest.

    When the caller supplies no criteria, a critic pass proposes them before the lock
    (M3). Provenance remains ``source='critic'``.
    """

    criteria = list(state.criteria)
    note = None
    if not criteria:
        criteria = propose_criteria(state.task.request, workdir=ctx.workdir)
        note = f"critic proposed {len(criteria)} criterion(ies)"

    manifest = state.manifest.model_copy(update={"criteria_hash": criteria_hash(criteria)})
    new_state = state.model_copy(
        update={"criteria": criteria, "manifest": manifest, "criteria_locked_at": now()}
    )
    return NodeOutcome(state=new_state, route="always", note=note)
