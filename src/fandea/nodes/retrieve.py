"""``retrieve``: federated memory query (specs §4, §5).

Procedural plane via Retriever (M1). Episodic dead ends + solved cases (M2). Affordance
tool cautions (M2). Control arm still returns an empty suppressed bundle.
"""

from __future__ import annotations

from contracts.run import MemoryBundle, MemoryElementRef, RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def retrieve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if state.arm == "control":
        bundle = MemoryBundle(suppressed=True)
        new_state = state.model_copy(update={"bundle": bundle})
        return NodeOutcome(state=new_state, route="always", note="control arm: retrieval suppressed")

    skills = []
    snapshot_id = None
    dropped = 0
    if ctx.retriever is not None:
        bundle, explanation = ctx.retriever.search(
            state.task.request,
            workdir=ctx.workdir,
            env_fingerprint=ctx.env_fingerprint,
            suppress=False,
        )
        skills = list(bundle.skills)
        snapshot_id = explanation.snapshot_id
        dropped = len(explanation.dropped)

    dead_ends: list[MemoryElementRef] = []
    cases: list[MemoryElementRef] = []
    if ctx.episodic is not None:
        for case in ctx.episodic.dead_ends_for(task_class=state.task.task_class, limit=3):
            dead_ends.append(
                MemoryElementRef(
                    plane="episodic",
                    ref=case.case_id,
                    summary=(case.dead_end.why_failed if case.dead_end else case.outcome),
                )
            )
        for row in reversed(ctx.episodic.list_index()):
            if row.get("outcome") != "solved":
                continue
            if state.task.task_class and row.get("task_class") != state.task.task_class:
                continue
            cases.append(
                MemoryElementRef(plane="episodic", ref=row["case_id"], summary="solved analogue")
            )
            if len(cases) >= 3:
                break

    tool_cautions: list[MemoryElementRef] = []
    if ctx.affordances is not None:
        for name, agg in ctx.affordances.tools.items():
            if agg.flake_rate >= 0.3 and agg.invocations >= 3:
                tool_cautions.append(
                    MemoryElementRef(
                        plane="affordance",
                        ref=name,
                        summary=f"flake_rate={agg.flake_rate:.2f}",
                        trust=1.0 - agg.flake_rate,
                    )
                )

    bundle = MemoryBundle(
        skills=skills,
        cases=cases,
        dead_ends=dead_ends,
        tool_cautions=tool_cautions,
    )
    updates: dict = {"bundle": bundle}
    if snapshot_id is not None:
        updates["manifest"] = state.manifest.model_copy(update={"index_snapshot_id": snapshot_id})
    new_state = state.model_copy(update=updates)
    note = (
        f"snapshot={snapshot_id} skills={len(skills)} dead_ends={len(dead_ends)} "
        f"cautions={len(tool_cautions)} dropped={dropped}"
    )
    return NodeOutcome(state=new_state, route="always", note=note)
