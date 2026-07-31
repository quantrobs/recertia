"""``distill``: extract a skill draft (M3) and record the solved attempt episodically (M2)."""

from __future__ import annotations

from contracts.run import ReusabilityVerdict, RunState
from fandea.memory.episodic import CaseRecord
from fandea.nodes.context import NodeContext, NodeOutcome


def distill(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if ctx.episodic is not None:
        approach = (
            f"skill:{state.chosen.skill_id}@v{state.chosen.version}"
            if state.chosen
            else f"strategy:{state.strategy or 'scratch'}"
        )
        case = CaseRecord(
            case_id=f"{ctx.run_id}-a{state.attempt_no}",
            run_id=ctx.run_id,
            attempt_no=state.attempt_no,
            task_class=state.task.task_class,
            request_excerpt=state.task.request[:200],
            outcome="solved",
            transcript_ref=state.transcript_ref,
            approach=approach,
            skill_id=state.chosen.skill_id if state.chosen else None,
            skill_version=state.chosen.version if state.chosen else None,
        )
        ctx.episodic.write(case)

    verdict = ReusabilityVerdict(
        verdict="one_off",
        parameterisable=False,
        context_free=False,
        checkable=True,
        not_duplicate=True,
        bounded=True,
        reason="M3 distillation not yet active; solved attempt recorded as one_off evidence.",
    )
    new_state = state.model_copy(update={"reusability": verdict})
    return NodeOutcome(state=new_state, route="one_off")
