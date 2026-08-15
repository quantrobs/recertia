"""``solve``: apply a skill (or scratch) via the tool runtime and write a transcript (M2).

Fallback order:
1. Explicit ``ctx.script`` (tests / golden override) — still recorded into a transcript.
2. ``apply``/``adapt`` with a chosen skill + ``SkillApplicator`` (wave-based tool execution).
3. ``scratch`` via the model client proposing a shell command, executed through the tool runtime.
4. Legacy ``["true"]`` no-op only when no M2 services are configured (M0/M1 tests).
   With tools/transcripts wired, scratch without a model fails loud.
"""

from __future__ import annotations

import functools
import time
from dataclasses import replace
from pathlib import Path

from contracts.budget import BudgetReservation, Spend, budget_excess
from contracts.failure import FailureSignal
from contracts.run import RunState
from recertia.memory.procedural.apply import script_from_skill
from recertia.nodes._util import now
from recertia.nodes.attempt import (
    AttemptMeter,
    RuntimeWindow,
    UsageDelta,
    completed,
    failed,
    record_new_affordances,
)
from recertia.nodes.context import NodeContext, NodeOutcome
from recertia.solver.transcript import TranscriptWriter


def solve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    attempt_no = state.attempt_no + 1

    # M6: when fan_out left dispatched branches, execute each branch workspace once.
    if state.branches and any(b.status == "dispatched" for b in state.branches):
        return _solve_branches(state, ctx, attempt_no)

    if ctx.applicator is not None and state.strategy in ("apply", "adapt") and state.chosen and ctx.store:
        return _solve_via_applicator(state, ctx, attempt_no)

    # P0-3: observe–act scratch loop (model sees command output within the attempt).
    if (
        ctx.script is None
        and state.strategy == "scratch"
        and ctx.model is not None
        and ctx.tools is not None
        and ctx.transcripts is not None
    ):
        return _solve_scratch_observe_act(state, ctx, attempt_no)

    try:
        script = _resolve_script(state, ctx)
    except ModelRequiredError as exc:
        return failed(
            state,
            AttemptMeter.open(state),
            signal=FailureSignal(
                source="solver",
                detail=f"environment: {exc}",
                at=now(),
                class_hint="environment",
            ),
            attempt_no=attempt_no,
            note="scratch requires a configured model",
        )

    if ctx.transcripts is not None and ctx.tools is not None:
        return _solve_script_via_tools(state, ctx, attempt_no, script)

    return _solve_legacy_script(state, ctx, attempt_no, script)


def _solve_branches(state: RunState, ctx: NodeContext, attempt_no: int) -> NodeOutcome:
    from contracts.criteria import CriterionResult
    from recertia.nodes.validate import _score_criterion_dict

    # Branch leases are being retired into parent spend here, so the parent must not also be
    # charged for still holding the reservation fan_out took out.
    meter = AttemptMeter.open(state, reserved=BudgetReservation())
    updated = []
    attempts_charged = 0
    for branch in state.branches:
        if branch.status not in ("dispatched", "running"):
            updated.append(branch)
            continue
        work = ctx.workdir / branch.branch_id
        work.mkdir(parents=True, exist_ok=True)
        script = ctx.script or ["true"]
        # Enforce the branch lease before spending tools — the lease is not advisory.
        projected = Spend(
            attempts=branch.spent.attempts + 1,
            tool_calls=branch.spent.tool_calls + len(script),
            tokens=branch.spent.tokens,
            wall_clock_s=branch.spent.wall_clock_s,
            cost_usd=branch.spent.cost_usd + 0.01 * (1 + len(script)),
        )
        branch_excess = budget_excess(
            branch.budget, projected, BudgetReservation(), BudgetReservation()
        )
        if branch_excess is not None:
            updated.append(
                branch.model_copy(
                    update={
                        "status": "timed_out",
                        "results": [
                            CriterionResult(
                                criterion_id="branch-budget",
                                kind="command",
                                passed=False,
                                weight=1.0,
                            )
                        ],
                        "workspace_ref": str(work),
                        "spent": projected,
                        "reserved": BudgetReservation(),
                    }
                )
            )
            # Wall clock comes from the meter's own clock, which spans the whole branch loop,
            # rather than from summing per-branch measurements.
            meter.charge(
                tool_calls=projected.tool_calls,
                tokens=projected.tokens,
                cost_usd=projected.cost_usd,
            )
            attempts_charged += projected.attempts
            continue
        ok = True
        started = time.monotonic()
        executed = 0
        for command in script:
            result = _run_container_command(command, work)
            executed += 1
            if result["returncode"] != 0:
                ok = False
                break
        # Decomposition branches own and score only their assigned criteria. Portfolio
        # branches retain their lightweight comparable score; the selected artifact is
        # subsequently validated as a whole by join.
        if branch.kind == "decomposition":
            owned = [c for c in state.criteria if c.id in branch.owned_criteria]
            branch_ctx = replace(ctx, workdir=work, node="validate")
            results = [
                CriterionResult.model_validate(_score_criterion_dict(criterion, branch_ctx))
                for criterion in owned
            ]
            ok = ok and all(result.passed for result in results if result.weight >= 1.0)
        else:
            results = [
                CriterionResult(criterion_id="branch-ok", kind="command", passed=ok, weight=1.0)
            ]
        cost = 0.01 * (1 + executed)
        elapsed = time.monotonic() - started
        branch_spent = Spend(
            attempts=1,
            tool_calls=executed,
            wall_clock_s=elapsed,
            cost_usd=cost,
        )
        meter.charge(
            tool_calls=branch_spent.tool_calls,
            tokens=branch_spent.tokens,
            cost_usd=branch_spent.cost_usd,
        )
        attempts_charged += branch_spent.attempts
        updated.append(
            branch.model_copy(
                update={
                    "status": "succeeded" if ok else "failed",
                    "results": results,
                    "cost_usd": cost,
                    "workspace_ref": str(work),
                    "spent": branch_spent,
                    "reserved": BudgetReservation(),
                }
            )
        )

    # Reconcile each lease into parent spend. This catches a runtime measurement that was
    # larger than its conservative admission estimate without hiding the actual spend.
    retired = {"reserved": BudgetReservation(), "branches": updated}
    exhausted = meter.preflight(attempts=attempts_charged)
    if exhausted is not None:
        return failed(
            state,
            meter,
            signal=FailureSignal(
                source="solver",
                detail=f"parent budget exceeded by branches: {exhausted}",
                at=now(),
                class_hint="budget",
            ),
            attempt_no=attempt_no,
            attempts=attempts_charged,
            note=f"budget exceeded: {exhausted}",
            updates={**retired, "transcript_ref": f"{ctx.run_id}/branches-{attempt_no}"},
        )

    return completed(
        state,
        meter,
        attempt_no=attempt_no,
        attempts=attempts_charged,
        transcript_ref=f"{ctx.run_id}/branches-{attempt_no}",
        note=f"ran {len(updated)} branches",
        updates=retired,
    )


def _solve_via_applicator(state: RunState, ctx: NodeContext, attempt_no: int) -> NodeOutcome:
    assert ctx.applicator is not None and ctx.store is not None and state.chosen is not None
    version = ctx.store.get_version(state.chosen.skill_id, state.chosen.version)
    params = dict(state.chosen.bound_parameters)
    # Fill defaults from the skill's parameter declarations.
    for p in version.parameters:
        if p.name not in params and p.default is not None:
            params[p.name] = p.default

    writer = (
        TranscriptWriter(ctx.transcripts, ctx.run_id, attempt_no)
        if ctx.transcripts is not None
        else None
    )
    # Local writer stub when transcripts aren't configured.
    if writer is None:
        from recertia.solver.transcript import TranscriptStore

        writer = TranscriptWriter(TranscriptStore(ctx.workdir / ".transcripts"), ctx.run_id, attempt_no)

    meter = AttemptMeter.open(state)
    window = RuntimeWindow(ctx)

    def _run() -> dict:
        result = ctx.applicator.apply(  # type: ignore[union-attr]
            version,
            params=params,
            workdir=ctx.workdir,
            run_id=ctx.run_id,
            attempt_no=attempt_no,
            transcript=writer,
        )
        # Persist a JSON-safe summary so at-least-once resume stays valid. Usage is measured
        # inside the operation so a replayed result still charges what it originally spent.
        return {
            "ok": result.ok,
            "transcript_ref": result.transcript_ref,
            "error": result.error,
            "merge_timeout": result.merge_timeout,
            "waves": [wr.wave.model_dump(mode="json") for wr in result.waves],
            "conflicts": [
                c.model_dump(mode="json") for wr in result.waves for c in wr.conflicts
            ],
            "usage": window.delta().as_dict(),
        }

    summary = ctx.op_once(0, _run)
    record_new_affordances(ctx, window)
    meter.charge_delta(UsageDelta.from_dict(summary.get("usage") or {}))

    from contracts.resources import ResourceConflict
    from contracts.run import StepWave

    waves = [StepWave.model_validate(w) for w in summary["waves"]]
    conflicts = [ResourceConflict.model_validate(c) for c in summary["conflicts"]]

    if not summary["ok"]:
        detail = summary["error"] or "skill application failed"
        if summary["merge_timeout"]:
            detail = f"claim timeout: {detail}"
        return failed(
            state,
            meter,
            signal=FailureSignal(source="solver", detail=detail, at=now()),
            attempt_no=attempt_no,
            note=f"applicator failed: {detail}",
            updates={
                "transcript_ref": summary["transcript_ref"],
                "step_waves": [*state.step_waves, *waves],
                "resource_conflicts": [*state.resource_conflicts, *conflicts],
            },
        )

    return completed(
        state,
        meter,
        attempt_no=attempt_no,
        transcript_ref=summary["transcript_ref"] or f"{ctx.run_id}/attempt-{attempt_no}",
        description="structured attempt transcript",
        updates={"step_waves": [*state.step_waves, *waves]},
    )


def _solve_script_via_tools(
    state: RunState, ctx: NodeContext, attempt_no: int, script: list[str]
) -> NodeOutcome:
    assert ctx.tools is not None
    writer = (
        TranscriptWriter(ctx.transcripts, ctx.run_id, attempt_no)
        if ctx.transcripts is not None
        else None
    )
    meter = AttemptMeter.open(state)
    for op_seq, command in enumerate(script):
        exhausted = meter.preflight(tool_calls=1)
        if exhausted is not None:
            return failed(
                state,
                meter,
                signal=FailureSignal(
                    source="solver",
                    detail=f"budget exhausted before tool dispatch: {exhausted}",
                    at=now(),
                    class_hint="budget",
                ),
                attempt_no=attempt_no,
                note=f"tool-call budget exhausted: {exhausted}",
                updates={"transcript_ref": writer.finalize() if writer else None},
            )

        window = RuntimeWindow(ctx)

        def _run(cmd: str = command, seq: int = op_seq, win: RuntimeWindow = window) -> dict:
            if writer:
                writer.event("tool", tool="shell", command=cmd)
            result = ctx.tools.invoke(  # type: ignore[union-attr]
                "shell", {"command": cmd}, workdir=ctx.workdir, step_id=f"script-{seq}"
            )
            return {
                "returncode": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "flaky": ctx.tools.is_flaky("shell") if ctx.tools else False,
                "usage": win.delta().as_dict(),
            }

        result = ctx.op_once(op_seq, _run)
        meter.charge_delta(UsageDelta.from_dict(result.get("usage") or {}))
        record_new_affordances(ctx, window)
        if result["returncode"] != 0:
            detail = f"step {op_seq} exited {result['returncode']}: {command}"
            if result.get("flaky"):
                detail = f"flaky tool=shell: {detail}"
            return failed(
                state,
                meter,
                signal=FailureSignal(source="solver", detail=detail, at=now()),
                attempt_no=attempt_no,
                note=f"solver-raised failure signal at step {op_seq}",
                updates={"transcript_ref": writer.finalize() if writer else None},
            )

    return completed(
        state,
        meter,
        attempt_no=attempt_no,
        transcript_ref=writer.finalize() if writer else f"{ctx.run_id}/attempt-{attempt_no}",
        description="scripted attempt transcript",
    )


def _solve_legacy_script(
    state: RunState, ctx: NodeContext, attempt_no: int, script: list[str]
) -> NodeOutcome:
    meter = AttemptMeter.open(state)
    for op_seq, command in enumerate(script):
        result = ctx.op_once(op_seq, functools.partial(_run_command, command, ctx))
        # One legacy command is one charge whether it ran now or replayed from the ledger.
        meter.charge(tool_calls=1)
        if result["returncode"] != 0:
            return failed(
                state,
                meter,
                signal=FailureSignal(
                    source="solver",
                    detail=f"step {op_seq} exited {result['returncode']}: {command}",
                    at=now(),
                ),
                attempt_no=attempt_no,
                note=f"solver-raised failure signal at step {op_seq}",
            )

    return completed(
        state,
        meter,
        attempt_no=attempt_no,
        transcript_ref=f"{ctx.run_id}/attempt-{attempt_no}",
        description="scripted attempt transcript",
    )


class ModelRequiredError(RuntimeError):
    """Scratch solving was selected but no model client is configured."""


def _scratch_max_steps() -> int:
    import os

    raw = os.environ.get("RECERTIA_SCRATCH_MAX_STEPS", "5")
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return 5


def _solve_scratch_observe_act(
    state: RunState, ctx: NodeContext, attempt_no: int
) -> NodeOutcome:
    """Bounded observe–act loop: model proposes → shell runs → model sees output."""

    assert ctx.model is not None and ctx.tools is not None
    from recertia.solver.command_policy import CommandPolicyError, assert_command_allowed

    writer = (
        TranscriptWriter(ctx.transcripts, ctx.run_id, attempt_no)
        if ctx.transcripts is not None
        else None
    )
    history: list[str] = []
    meter = AttemptMeter.open(state)
    last_error: str | None = None
    max_steps = _scratch_max_steps()

    for step in range(max_steps):
        exhausted = meter.preflight(tool_calls=1)
        if exhausted is not None:
            return failed(
                state,
                meter,
                signal=FailureSignal(
                    source="solver",
                    detail=f"budget exhausted before tool dispatch: {exhausted}",
                    at=now(),
                    class_hint="budget",
                ),
                attempt_no=attempt_no,
                note=f"scratch budget exhausted: {exhausted}",
                updates={"transcript_ref": writer.finalize() if writer else None},
            )

        history_block = "\n".join(history[-6:]) if history else "(no prior steps)"
        prompt = (
            f"Task: {state.task.request}\n"
            f"Workspace: {ctx.workdir}\n"
            f"Prior steps:\n{history_block}\n"
            "Propose exactly one shell command that progresses the task. "
            "Reply with only the command, no markdown. "
            "If the task appears done, reply with: true"
        )
        try:
            response = ctx.model.complete(
                prompt,
                system="Return a single shell command only.",
            )
        except Exception as exc:  # noqa: BLE001 — solver boundary
            return failed(
                state,
                meter,
                signal=FailureSignal(
                    source="solver",
                    detail=f"environment: model error during scratch: {exc}",
                    at=now(),
                    class_hint="environment",
                ),
                attempt_no=attempt_no,
                note="scratch model error",
                updates={"transcript_ref": writer.finalize() if writer else None},
            )
        # The model call is outside op_once, so it is re-issued on resume and charged directly.
        meter.charge(
            tokens=response.prompt_tokens + response.completion_tokens,
            cost_usd=response.cost_usd,
        )
        command = response.text.strip().splitlines()[0].strip().strip("`")
        if not command:
            last_error = "empty command from model"
            continue
        try:
            command = assert_command_allowed(command)
        except CommandPolicyError as exc:
            last_error = str(exc)
            history.append(f"$ {command}\n[refused] {exc}")
            if writer:
                writer.event("tool", tool="shell", command=command, refused=str(exc))
            continue

        window = RuntimeWindow(ctx)

        def _run(cmd: str = command, seq: int = step, win: RuntimeWindow = window) -> dict:
            if writer:
                writer.event("tool", tool="shell", command=cmd, step=seq)
            result = ctx.tools.invoke(  # type: ignore[union-attr]
                "shell", {"command": cmd}, workdir=ctx.workdir, step_id=f"scratch-{seq}"
            )
            return {
                "returncode": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "usage": win.delta().as_dict(),
            }

        result = ctx.op_once(step, _run)
        meter.charge_delta(UsageDelta.from_dict(result.get("usage") or {}))
        record_new_affordances(ctx, window)
        history.append(
            f"$ {command}\nexit={result['returncode']}\n"
            f"stdout:\n{result['stdout'][-1500:]}\nstderr:\n{result['stderr'][-800:]}"
        )
        if result["returncode"] != 0:
            last_error = (
                f"step {step} exited {result['returncode']}: {command}"
            )
            continue
        # Successful command: leave the attempt for validate to judge.
        # (A final `true` also ends the loop cleanly.)
        return completed(
            state,
            meter,
            attempt_no=attempt_no,
            transcript_ref=writer.finalize() if writer else f"{ctx.run_id}/attempt-{attempt_no}",
            description="scratch observe-act transcript",
            note=f"scratch observe-act completed after {step + 1} step(s)",
        )

    return failed(
        state,
        meter,
        signal=FailureSignal(
            source="solver",
            detail=last_error or f"scratch observe-act exhausted {max_steps} steps",
            at=now(),
        ),
        attempt_no=attempt_no,
        note="scratch observe-act exhausted without success",
        updates={"transcript_ref": writer.finalize() if writer else None},
    )


def _resolve_script(state: RunState, ctx: NodeContext) -> list[str]:
    if ctx.script is not None:
        return ctx.script
    if state.strategy in ("apply", "adapt") and state.chosen is not None and ctx.store is not None:
        version = ctx.store.get_version(state.chosen.skill_id, state.chosen.version)
        params = dict(state.chosen.bound_parameters)
        for p in version.parameters:
            if p.name not in params and p.default is not None:
                params[p.name] = p.default
        from recertia.solver.apply import bind_parameters

        raw = script_from_skill(version)
        return [bind_parameters(cmd, params) for cmd in raw]
    if state.strategy == "scratch" and ctx.model is not None:
        # Legacy single-shot path (no tools/transcripts wired).
        response = ctx.model.complete(
            f"Propose a single shell command to: {state.task.request}\n"
            "Reply with only the command, no markdown."
        )
        return [response.text.strip().splitlines()[0]]
    if state.strategy == "scratch" and (ctx.tools is not None or ctx.transcripts is not None):
        raise ModelRequiredError(
            "scratch solving requires a model client; set RECERTIA_MODEL_PROVIDER "
            "and credentials (or --model provider:id), or pass an explicit script / "
            "RECERTIA_ALLOW_STUB_MODEL=1 for offline demos"
        )
    return ["true"]


def _run_command(command: str, ctx: NodeContext) -> dict:
    return _run_container_command(command, ctx.workdir)


def _run_container_command(command: str, workdir: Path) -> dict:
    """Execute solver commands only through the approved OCI sandbox."""

    from recertia.solver.container import run_configured_command
    from recertia.solver.sandbox import SandboxError

    try:
        proc = run_configured_command(command, workdir=workdir, timeout_s=60)
    except SandboxError as exc:
        return {"returncode": 126, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }
