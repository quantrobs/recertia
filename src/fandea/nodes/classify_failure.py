"""``classify_failure``: assign a failure class from the taxonomy (specs §4, §16). M0 stub.

M0 has no skill applied (``plan`` always chooses ``scratch``) and no fan-out, so the
``retrieval``, ``plan``, and ``merge`` classes are structurally unreachable here — they need a
chosen skill or a branch to be about. What M0 *can* diagnose honestly from a raised
``FailureSignal`` alone:

- ``source="solver"`` (raised before validation ever ran) -> ``tool`` — the only pre-validation
  class M0's scripted solve can distinguish; finer environment/tool separation needs the tool
  registry (M2).
- budget already exhausted -> ``budget``, regardless of source.
- ``source="validator"`` with a failed required criterion whose own sensitivity proof does not
  reject its negative fixture -> ``criteria`` ("sensitivity proof invalid", specs §16) — a
  cheap, real diagnostic using data the criterion already carries, not a guess.
- Any other validator-raised failure -> ``execution`` (retryable); the route table's own
  "no progress across two identical attempts" check (``contracts.graph._budget_remains_with_progress``)
  is what actually stops a genuinely unsatisfiable ``execution``-classified loop from running
  forever, which is exactly the M0 done-when this satisfies.
"""

from __future__ import annotations

from contracts.failure import FailureVerdict
from contracts.graph import legal_routes
from contracts.run import RunState
from fandea.nodes.context import NodeContext, NodeOutcome


def classify_failure(state: RunState, ctx: NodeContext) -> NodeOutcome:
    signal = state.failure_signal
    if signal is None:
        raise ValueError("classify_failure requires a FailureSignal on the run state (ADR-0008)")

    if state.spent.attempts >= state.budget.max_attempts:
        evidence = (
            f"spent.attempts={state.spent.attempts} >= "
            f"budget.max_attempts={state.budget.max_attempts}"
        )
        failure = FailureVerdict(
            failure_class="budget",
            evidence=[evidence],
            counts_against_trust=False,
            escalate_to_human=False,
        )
    elif signal.source == "solver":
        failure = FailureVerdict(
            failure_class="tool",
            evidence=[signal.detail],
            counts_against_trust=False,
            escalate_to_human=False,
        )
    elif _has_invalid_sensitivity_proof(state):
        failure = FailureVerdict(
            failure_class="criteria",
            evidence=_invalid_proof_evidence(state),
            counts_against_trust=False,
            escalate_to_human=True,
        )
    else:
        failure = FailureVerdict(
            failure_class="execution",
            evidence=[r.criterion_id for r in state.results if not r.passed],
            counts_against_trust=True,
            escalate_to_human=False,
        )

    assert failure.is_consistent, f"classify_failure produced an internally inconsistent verdict: {failure!r}"

    new_state = state.model_copy(update={"failure": failure})
    legal = legal_routes("classify_failure", new_state)
    assert len(legal) == 1, f"ambiguous routes out of classify_failure: {[r.predicate_name for r in legal]}"
    return NodeOutcome(
        state=new_state, route=legal[0].predicate_name, note=f"classified as {failure.failure_class!r}"
    )


def _has_invalid_sensitivity_proof(state: RunState) -> bool:
    failed_ids = {r.criterion_id for r in state.results if not r.passed}
    for criterion in state.criteria:
        if criterion.id in failed_ids and criterion.is_required and criterion.sensitivity_proof is not None:
            if not criterion.sensitivity_proof.rejected:
                return True
    return False


def _invalid_proof_evidence(state: RunState) -> list[str]:
    failed_ids = {r.criterion_id for r in state.results if not r.passed}
    return [
        f"{c.id}: sensitivity_proof.rejected=False (does not reject its own negative fixture)"
        for c in state.criteria
        if c.id in failed_ids and c.sensitivity_proof is not None and not c.sensitivity_proof.rejected
    ]
