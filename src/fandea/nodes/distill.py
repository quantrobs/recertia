"""``distill``: extract a skill draft and facts from a solved run (specs §4). M0 stub.

Real distillation (parameter extraction, generalisation, criteria proposal, fact extraction)
needs a model and lands in M3. M0 always records ``one_off`` — an honest verdict, not a
placeholder: a scripted, non-generalised attempt genuinely is not reusable yet. This still
exercises the real route table (``distill -> finalize``, terminal ``solved``), just without
``review``/``store`` in the loop.
"""

from __future__ import annotations

from contracts.run import ReusabilityVerdict, RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def distill(state: RunState, ctx: NodeContext) -> NodeOutcome:
    verdict = ReusabilityVerdict(
        verdict="one_off",
        parameterisable=False,
        context_free=False,
        checkable=True,
        not_duplicate=True,
        bounded=True,
        reason="M0 stub: distillation lands in M3; every M0 run is recorded as one_off evidence.",
    )
    new_state = state.model_copy(update={"reusability": verdict})
    return NodeOutcome(state=new_state, route="one_off")
