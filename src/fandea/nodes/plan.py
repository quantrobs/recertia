"""``plan``: choose apply/adapt/scratch/abstain/portfolio/decomposition (M1+M6).

Variant B: prefer ``Goal.strategy_hint`` over request-string prefixes when a Goal is present.
"""

from __future__ import annotations

from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome
from fandea.nodes.fan_out import _partition_criteria

APPLY_THRESHOLD = 0.48
ADAPT_THRESHOLD = 0.35
PORTFOLIO_GAP = 0.08  # top two scores within this → portfolio


def plan(state: RunState, ctx: NodeContext) -> NodeOutcome:
    # Explicit strategy from Goal (Variant B) takes precedence.
    hint = None
    if state.task.goal is not None:
        hint = state.task.goal.strategy_hint

    request = state.task.request or ""

    if hint == "abstain" or request.startswith("ABSTAIN:"):
        new_state = state.model_copy(
            update={
                "strategy": "abstain",
                "strategy_reason": "caller requested abstention",
                "predicted_success": 0.0,
            }
        )
        return NodeOutcome(state=new_state, route="abstain")

    if hint == "decomposition" or request.startswith("DECOMPOSE:") or (
        not request.startswith("PORTFOLIO:") and "DECOMPOSE:" in request
    ):
        if _partition_criteria(state) is None:
            new_state = state.model_copy(
                update={
                    "strategy": "scratch",
                    "strategy_reason": "decomposition refused: criteria cannot be partitioned",
                    "predicted_success": 0.4,
                }
            )
            return NodeOutcome(state=new_state, route="single_strategy")
        new_state = state.model_copy(
            update={
                "strategy": "decomposition",
                "strategy_reason": "caller requested decomposition with partitionable criteria",
                "predicted_success": 0.55,
            }
        )
        return NodeOutcome(state=new_state, route="fan_out_strategy")

    if hint == "portfolio" or request.startswith("PORTFOLIO:") or request.startswith("AMBIGUOUS:"):
        new_state = state.model_copy(
            update={
                "strategy": "portfolio",
                "strategy_reason": "caller marked task ambiguous; portfolio fan-out",
                "predicted_success": 0.5,
            }
        )
        return NodeOutcome(state=new_state, route="fan_out_strategy")

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
    if len(skills) >= 2 and abs(skills[0].score - skills[1].score) <= PORTFOLIO_GAP:
        if skills[0].score >= ADAPT_THRESHOLD:
            new_state = state.model_copy(
                update={
                    "strategy": "portfolio",
                    "strategy_reason": (
                        f"ambiguous top skills {skills[0].skill_id} vs {skills[1].skill_id}"
                    ),
                    "predicted_success": top.score,
                    "chosen": top,
                }
            )
            return NodeOutcome(state=new_state, route="fan_out_strategy")

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
