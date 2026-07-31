"""``plan``: choose a strategy (specs §4). M1: ``apply`` / ``adapt`` / ``scratch`` / ``abstain``.

Rules (M1, no model calibration yet — thresholds are explicit and testable):

- Empty bundle → ``scratch`` (novel / no applicable skill).
- Top candidate score ≥ ``APPLY_THRESHOLD`` → ``apply`` that candidate.
- Top candidate score ≥ ``ADAPT_THRESHOLD`` → ``adapt`` (close, but needs parameter/step edits;
  M1 still runs the skill's script, recording the adapt intent for M2's real editor).
- Otherwise → ``scratch``.
- ``abstain`` is reserved for an explicit caller flag on the task (``task_class == "abstain"``
  is not used); M1 exposes it when the request literally starts with ``ABSTAIN:``.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome

APPLY_THRESHOLD = 0.48
ADAPT_THRESHOLD = 0.35


def plan(state: RunState, ctx: NodeContext) -> NodeOutcome:
    if state.task.request.startswith("ABSTAIN:"):
        new_state = state.model_copy(
            update={
                "strategy": "abstain",
                "strategy_reason": "caller requested abstention",
                "predicted_success": 0.0,
            }
        )
        return NodeOutcome(state=new_state, route="abstain")

    skills = state.bundle.skills
    if not skills:
        new_state = state.model_copy(
            update={
                "strategy": "scratch",
                "strategy_reason": "empty memory bundle; solve from scratch",
                "predicted_success": 0.4,
                "chosen": None,
            }
        )
        return NodeOutcome(state=new_state, route="single_strategy")

    top = skills[0]
    if top.score >= APPLY_THRESHOLD:
        new_state = state.model_copy(
            update={
                "strategy": "apply",
                "strategy_reason": f"top candidate {top.skill_id}@v{top.version} score={top.score}",
                "predicted_success": min(0.95, top.score),
                "chosen": top,
            }
        )
        return NodeOutcome(state=new_state, route="single_strategy")

    if top.score >= ADAPT_THRESHOLD:
        new_state = state.model_copy(
            update={
                "strategy": "adapt",
                "strategy_reason": (
                    f"top candidate {top.skill_id}@v{top.version} score={top.score} "
                    f"below apply threshold {APPLY_THRESHOLD}"
                ),
                "predicted_success": top.score,
                "chosen": top,
            }
        )
        return NodeOutcome(state=new_state, route="single_strategy")

    new_state = state.model_copy(
        update={
            "strategy": "scratch",
            "strategy_reason": f"top score {top.score} below adapt threshold {ADAPT_THRESHOLD}",
            "predicted_success": 0.4,
            "chosen": None,
        }
    )
    return NodeOutcome(state=new_state, route="single_strategy")
