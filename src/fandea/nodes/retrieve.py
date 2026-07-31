"""``retrieve``: federated memory query (specs §4, §5).

M1 wires the procedural plane through :class:`~fandea.retrieval.pipeline.Retriever`. Other
planes (facts, cases, affordances) still return empty until M2+. When ``arm == "control"`` the
bundle is empty and ``suppressed=True`` (specs §5 / §19). When no retriever is configured
(M0-style tests), returns an empty unsuppressed bundle — the honest "no memory" baseline.
"""

from __future__ import annotations

from contracts.run import MemoryBundle, RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def retrieve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if state.arm == "control":
        bundle = MemoryBundle(suppressed=True)
        new_state = state.model_copy(update={"bundle": bundle})
        return NodeOutcome(state=new_state, route="always", note="control arm: retrieval suppressed")

    if ctx.retriever is None:
        return NodeOutcome(state=state, route="always", note="no retriever configured; empty bundle")

    bundle, explanation = ctx.retriever.search(
        state.task.request,
        workdir=ctx.workdir,
        env_fingerprint=ctx.env_fingerprint,
        suppress=False,
    )
    manifest = state.manifest.model_copy(update={"index_snapshot_id": explanation.snapshot_id})
    new_state = state.model_copy(update={"bundle": bundle, "manifest": manifest})
    note = (
        f"snapshot={explanation.snapshot_id} "
        f"returned={len(bundle.skills)} "
        f"dropped={len(explanation.dropped)}"
    )
    return NodeOutcome(state=new_state, route="always", note=note)
