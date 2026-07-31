"""``validate``: score locked criteria against the attempt (specs §4, §15.2). M0 stub.

Only ``kind="command"`` criteria are supported — the only kind M0's golden fixtures use.
``judge`` (fresh-context model scoring) and ``metric``/``schema``/``assertion`` land with the
milestones that need them (M3+).

Implements the M0-pulled-forward sensitivity-proof *check* (refactor-plan B6): a required
criterion (``weight >= 1.0``) without a proof that rejects a known-bad fixture
(``sensitivity_proof.rejected == True``) is downgraded to advisory — it is still executed for
real, but its outcome cannot gate routing (specs §15.2). This is implemented by recording its
result as ``passed=True`` for the required-set computation the route table performs
(``contracts.graph._required_criteria_pass``, which cannot see proof status — see
``docs/refactor-plan.md`` R3), while the *actual* outcome is preserved in ``output_excerpt``
and surfaced in the node's ``note`` (which the orchestrator writes into the route log).
"""

from __future__ import annotations

import functools
import subprocess

from contracts.criteria import CriterionResult, TaskCriterion
from contracts.failure import FailureSignal
from contracts.run import RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def validate(state: RunState, ctx: NodeContext) -> NodeOutcome:
    results: list[CriterionResult] = []
    downgrade_notes: list[str] = []
    any_effectively_required_failed = False

    for op_seq, criterion in enumerate(state.criteria):
        if criterion.kind != "command":
            raise ValueError(
                f"M0 validate only supports kind='command' criteria; got {criterion.kind!r} "
                f"for criterion {criterion.id!r} (later milestones add assertion/schema/metric/judge)"
            )

        outcome = ctx.op_once(op_seq, functools.partial(_run_criterion, criterion, ctx))
        actual_passed = outcome["returncode"] == criterion.expect_exit
        effectively_required = criterion.is_required and criterion.is_preregistered_and_proven

        if criterion.is_required and not effectively_required:
            recorded_passed = True  # advisory downgrade: never gates routing (specs §15.2)
            downgrade_notes.append(
                f"{criterion.id}: required, no valid sensitivity_proof -> advisory "
                f"(actual={'pass' if actual_passed else 'fail'})"
            )
        else:
            recorded_passed = actual_passed
            if criterion.is_required and not actual_passed:
                any_effectively_required_failed = True

        results.append(
            CriterionResult(
                criterion_id=criterion.id,
                kind=criterion.kind,
                passed=recorded_passed,
                weight=criterion.weight,
                exit_code=outcome["returncode"],
                output_excerpt=(outcome["stdout"] + outcome["stderr"])[-2000:],
                duration_s=0.0,
            )
        )

    failure_signal = None
    if any_effectively_required_failed:
        failure_signal = FailureSignal(
            source="validator", detail="a required, proven criterion failed", at=now()
        )

    new_state = state.model_copy(
        update={
            "results": results,
            "results_history": [*state.results_history, results],
            "failure_signal": failure_signal,
        }
    )

    route = "no_branches_and_failing" if failure_signal is not None else "no_branches_and_passing"
    note = "; ".join(downgrade_notes) if downgrade_notes else None
    return NodeOutcome(state=new_state, route=route, note=note)


def _run_criterion(criterion: TaskCriterion, ctx: NodeContext) -> dict:
    assert criterion.run is not None  # guaranteed by kind="command"'s field-requirement validator
    proc = subprocess.run(
        criterion.run,
        shell=True,
        cwd=ctx.workdir,
        capture_output=True,
        text=True,
        timeout=criterion.timeout_s,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
