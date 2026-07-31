"""``validate``: score locked criteria against the attempt (specs §4, §15.2, §26.3).

Supports ``command``, ``assertion``, and ``judge``. Judges run in an isolated
artifact+rubric context with ``context_hash`` recorded so isolation is testable.
"""

from __future__ import annotations

import functools
from pathlib import Path

from contracts.criteria import CriterionResult, TaskCriterion
from contracts.failure import FailureSignal
from contracts.run import RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome
from fandea.validation.judge import assert_distinct_lenses, evaluate_judge


def validate(state: RunState, ctx: NodeContext) -> NodeOutcome:
    results, failure_signal, downgrade_notes = score_criteria(state, ctx)
    new_state = state.model_copy(
        update={
            "results": results,
            "results_history": [*state.results_history, results],
            "failure_signal": failure_signal,
        }
    )

    route = "no_branches_and_failing" if failure_signal is not None else "no_branches_and_passing"
    if state.branches:
        route = "has_branches"
    note = "; ".join(downgrade_notes) if downgrade_notes else None
    return NodeOutcome(state=new_state, route=route, note=note)


def score_criteria(
    state: RunState, ctx: NodeContext, *, op_offset: int = 0
) -> tuple[list[CriterionResult], FailureSignal | None, list[str]]:
    """Score a state against ``ctx.workdir`` for normal and post-merge validation."""

    results: list[CriterionResult] = []
    downgrade_notes: list[str] = []
    any_effectively_required_failed = False

    assert_distinct_lenses(list(state.criteria))

    for op_seq, criterion in enumerate(state.criteria, start=op_offset):
        raw = ctx.op_once(op_seq, functools.partial(_score_criterion_dict, criterion, ctx))
        outcome_result = CriterionResult.model_validate(raw)
        actual_passed = outcome_result.passed
        effectively_required = criterion.is_required and criterion.is_preregistered_and_proven

        if criterion.is_required and not effectively_required:
            recorded_passed = True  # advisory downgrade: never gates routing (specs §15.2)
            downgrade_notes.append(
                f"{criterion.id}: required, no valid sensitivity_proof -> advisory "
                f"(actual={'pass' if actual_passed else 'fail'})"
            )
            # Preserve isolation evidence even when advisory.
            results.append(
                outcome_result.model_copy(
                    update={
                        "passed": recorded_passed,
                        "output_excerpt": (
                            f"[advisory] actual={'pass' if actual_passed else 'fail'}; "
                            + outcome_result.output_excerpt
                        )[:2000],
                    }
                )
            )
        else:
            results.append(outcome_result)
            if criterion.is_required and not actual_passed:
                any_effectively_required_failed = True

    failure_signal = None
    if any_effectively_required_failed:
        failure_signal = FailureSignal(
            source="validator", detail="a required, proven criterion failed", at=now()
        )

    return results, failure_signal, downgrade_notes


def _score_criterion_dict(criterion: TaskCriterion, ctx: NodeContext) -> dict:
    return _score_criterion(criterion, ctx).model_dump(mode="json")


def _score_criterion(criterion: TaskCriterion, ctx: NodeContext) -> CriterionResult:
    if criterion.kind == "command":
        return _run_command(criterion, ctx)
    if criterion.kind == "assertion":
        return _run_assertion(criterion, ctx)
    if criterion.kind == "judge":
        if ctx.verifier_model is None:
            raise ValueError(
                f"judge criterion {criterion.id!r} requires an independent verifier model"
            )
        if ctx.verifier_model is ctx.model:
            raise ValueError("solver model cannot judge its own artifact")
        return evaluate_judge(criterion, workdir=ctx.workdir, model=ctx.verifier_model)
    raise ValueError(
        f"validate does not yet support kind={criterion.kind!r} for criterion {criterion.id!r}"
    )


def _run_command(criterion: TaskCriterion, ctx: NodeContext) -> CriterionResult:
    assert criterion.run is not None
    from fandea.solver.container import run_configured_command
    from fandea.solver.sandbox import SandboxError

    try:
        proc = run_configured_command(criterion.run, workdir=ctx.workdir, timeout_s=criterion.timeout_s)
        exit_code, output = proc.returncode, proc.stdout + proc.stderr
    except SandboxError as exc:
        exit_code, output = 126, str(exc)
    return CriterionResult(
        criterion_id=criterion.id,
        kind="command",
        passed=exit_code == criterion.expect_exit,
        weight=criterion.weight,
        exit_code=exit_code,
        output_excerpt=output[-2000:],
        duration_s=0.0,
    )


def _run_assertion(criterion: TaskCriterion, ctx: NodeContext) -> CriterionResult:
    assert criterion.expr is not None
    ns = {"workdir": ctx.workdir, "Path": Path}
    try:
        passed = bool(eval(criterion.expr, {"__builtins__": {}}, ns))  # noqa: S307
        excerpt = f"assertion {criterion.expr!r} => {passed}"
        errored = False
    except Exception as exc:  # noqa: BLE001
        passed = False
        excerpt = f"assertion error: {exc}"
        errored = True
    return CriterionResult(
        criterion_id=criterion.id,
        kind="assertion",
        passed=passed,
        weight=criterion.weight,
        output_excerpt=excerpt[:2000],
        errored=errored,
    )
