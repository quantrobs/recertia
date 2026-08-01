"""``record_dead_end``: write a failed attempt to episodic memory (specs §4, §13.3)."""

from __future__ import annotations

from contracts.run import RunState
from recertia.memory.episodic import CaseRecord, DeadEnd
from recertia.nodes.context import NodeContext, NodeOutcome


def record_dead_end(state: RunState, ctx: NodeContext) -> NodeOutcome:
    failure_class = state.failure.failure_class if state.failure else "unknown"
    approach = (
        f"skill:{state.chosen.skill_id}@v{state.chosen.version}"
        if state.chosen
        else f"strategy:{state.strategy or 'scratch'}"
    )
    note = f"dead end recorded: failure_class={failure_class!r}"

    # Same firewall as distill: control / shadow / eval_fixture must not poison episodic memory.
    if state.task.is_eval_fixture:
        return NodeOutcome(
            state=state,
            route="always",
            note=f"{note}; eval firewall: episodic write suppressed",
        )
    if state.arm in ("control", "shadow"):
        return NodeOutcome(
            state=state,
            route="always",
            note=f"{note}; {state.arm} arm: episodic write suppressed",
        )

    if ctx.episodic is not None:
        case = CaseRecord(
            case_id=f"{ctx.run_id}-a{state.attempt_no}",
            run_id=ctx.run_id,
            attempt_no=state.attempt_no,
            task_class=state.task.task_class,
            request_excerpt=(state.task.request or "")[:200],
            outcome="failed",
            failure_class=failure_class if failure_class != "unknown" else None,
            dead_end=DeadEnd(
                approach=approach,
                why_failed=_why_failed(state, failure_class),
                evidence_ref=state.transcript_ref,
            ),
            transcript_ref=state.transcript_ref,
            approach=approach,
            skill_id=state.chosen.skill_id if state.chosen else None,
            skill_version=state.chosen.version if state.chosen else None,
        )
        ref = ctx.episodic.write(case)
        note = f"{note} case_hash={ref}"

    return NodeOutcome(state=state, route="always", note=note)


def _why_failed(state: RunState, failure_class: str) -> str:
    if state.failure_signal:
        return state.failure_signal.detail
    if state.failure and state.failure.evidence:
        return state.failure.evidence[0]
    return failure_class
