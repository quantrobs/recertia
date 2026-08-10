"""``retrieve``: federated memory query (specs §4, §5).

Procedural plane via Retriever (M1). Episodic dead ends + solved cases (M2). Affordance
tool cautions (M2). Control arm still returns an empty suppressed bundle.
"""

from __future__ import annotations

from contracts.run import MemoryBundle, MemoryElementRef, RunState, Task
from recertia.nodes.context import NodeContext, NodeOutcome


def retrieval_query(*, request: str | None, goal_context: str | None, goal_terms: str = "") -> str:
    """Build a non-None retrieval query from request, goal context, or goal terms."""

    if request is not None and request.strip():
        return request.strip()
    if goal_context is not None and goal_context.strip():
        return goal_context.strip()
    if goal_terms.strip():
        return goal_terms.strip()
    return ""


def _query_for(task: Task) -> str:
    """Non-None retrieval string for goal-only runs (no request / context)."""

    goal_terms = ""
    if task.goal is not None:
        parts: list[str] = []
        for desired in task.goal.desired:
            parts.append(desired.id)
            if desired.path:
                parts.append(desired.path)
            if desired.run:
                parts.append(desired.run)
            if desired.pattern:
                parts.append(desired.pattern)
        goal_terms = " ".join(parts)
        context = task.goal.context
    else:
        context = None
    return retrieval_query(request=task.request, goal_context=context, goal_terms=goal_terms)


def retrieve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if state.arm == "control":
        # Still pin the library snapshot so control observations compare against the
        # same index the treatment arm would have queried.
        snapshot_id = None
        if ctx.retriever is not None:
            snapshot_id = ctx.retriever.snapshot_id()
        bundle = MemoryBundle(suppressed=True)
        updates: dict = {"bundle": bundle}
        if snapshot_id is not None:
            updates["manifest"] = state.manifest.model_copy(
                update={"index_snapshot_id": snapshot_id}
            )
        new_state = state.model_copy(update=updates)
        return NodeOutcome(
            state=new_state,
            route="always",
            note=f"control arm: retrieval suppressed snapshot={snapshot_id}",
        )

    query = _query_for(state.task)
    skills = []
    snapshot_id = None
    dropped = 0
    if ctx.retriever is not None:
        bundle, explanation = ctx.retriever.search(
            query,
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
        for case_id in ctx.episodic.solved_case_ids_for(
            task_class=state.task.task_class, limit=3
        ):
            cases.append(
                MemoryElementRef(plane="episodic", ref=case_id, summary="solved analogue")
            )

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

    facts: list[MemoryElementRef] = []
    if ctx.facts is not None:
        for fact in ctx.facts.retrieve(query, limit=10):
            facts.append(
                MemoryElementRef(
                    plane="semantic",
                    ref=fact.fact_id,
                    summary=fact.assertion[:200],
                    trust=fact.confidence,
                )
            )

    bundle = MemoryBundle(
        skills=skills,
        facts=facts,
        cases=cases,
        dead_ends=dead_ends,
        tool_cautions=tool_cautions,
    )
    state_updates: dict = {"bundle": bundle}
    if snapshot_id is not None:
        state_updates["manifest"] = state.manifest.model_copy(
            update={"index_snapshot_id": snapshot_id}
        )
    new_state = state.model_copy(update=state_updates)
    note = (
        f"snapshot={snapshot_id} skills={len(skills)} dead_ends={len(dead_ends)} "
        f"cautions={len(tool_cautions)} dropped={dropped}"
    )
    return NodeOutcome(state=new_state, route="always", note=note)
