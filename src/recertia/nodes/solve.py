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
from contracts.run import Artifact, RunState
from recertia.memory.procedural.apply import script_from_skill
from recertia.nodes._util import now
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
        signal = FailureSignal(
            source="solver",
            detail=f"environment: {exc}",
            at=now(),
            class_hint="environment",
        )
        return NodeOutcome(
            state=state.model_copy(
                update={
                    "attempt_no": attempt_no,
                    "spent": state.spent.model_copy(
                        update={"attempts": state.spent.attempts + 1}
                    ),
                    "failure_signal": signal,
                }
            ),
            route="pre_validation_failure_signal",
            note="scratch requires a configured model",
        )

    if ctx.transcripts is not None and ctx.tools is not None:
        return _solve_script_via_tools(state, ctx, attempt_no, script)

    return _solve_legacy_script(state, ctx, attempt_no, script)


def _solve_branches(state: RunState, ctx: NodeContext, attempt_no: int) -> NodeOutcome:
    from contracts.criteria import CriterionResult
    from recertia.nodes.validate import _score_criterion_dict

    updated = []
    added = Spend()
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
            added = Spend(
                attempts=added.attempts + projected.attempts,
                tool_calls=added.tool_calls + projected.tool_calls,
                wall_clock_s=added.wall_clock_s + projected.wall_clock_s,
                cost_usd=added.cost_usd + projected.cost_usd,
            )
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
        added = Spend(
            attempts=added.attempts + branch_spent.attempts,
            tool_calls=added.tool_calls + branch_spent.tool_calls,
            wall_clock_s=added.wall_clock_s + branch_spent.wall_clock_s,
            cost_usd=added.cost_usd + branch_spent.cost_usd,
        )
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
    spent = state.spent.model_copy(
        update={
            "attempts": state.spent.attempts + added.attempts,
            "tool_calls": state.spent.tool_calls + added.tool_calls,
            "tokens": state.spent.tokens + added.tokens,
            "wall_clock_s": state.spent.wall_clock_s + added.wall_clock_s,
            "cost_usd": state.spent.cost_usd + added.cost_usd,
        }
    )
    exhausted = budget_excess(state.budget, spent, BudgetReservation(), BudgetReservation())
    if exhausted is not None:
        signal = FailureSignal(
            source="solver",
            detail=f"parent budget exceeded by branches: {exhausted}",
            at=now(),
            class_hint="budget",
        )
        new_state = state.model_copy(
            update={
                "attempt_no": attempt_no,
                "spent": spent,
                "reserved": BudgetReservation(),
                "branches": updated,
                "failure_signal": signal,
                "transcript_ref": f"{ctx.run_id}/branches-{attempt_no}",
            }
        )
        return NodeOutcome(
            state=new_state,
            route="pre_validation_failure_signal",
            note=f"budget exceeded: {exhausted}",
        )

    new_state = state.model_copy(
        update={
            "attempt_no": attempt_no,
            "spent": spent,
            "reserved": BudgetReservation(),
            "branches": updated,
            "transcript_ref": f"{ctx.run_id}/branches-{attempt_no}",
            "failure_signal": None,
        }
    )
    return NodeOutcome(state=new_state, route="attempt_completed", note=f"ran {len(updated)} branches")


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

    def _run() -> dict:
        result = ctx.applicator.apply(  # type: ignore[union-attr]
            version,
            params=params,
            workdir=ctx.workdir,
            run_id=ctx.run_id,
            attempt_no=attempt_no,
            transcript=writer,
        )
        # Persist a JSON-safe summary so at-least-once resume stays valid.
        return {
            "ok": result.ok,
            "transcript_ref": result.transcript_ref,
            "error": result.error,
            "merge_timeout": result.merge_timeout,
            "waves": [wr.wave.model_dump(mode="json") for wr in result.waves],
            "conflicts": [
                c.model_dump(mode="json") for wr in result.waves for c in wr.conflicts
            ],
            "tool_invocations": len(ctx.tools.invocations) if ctx.tools else 0,
        }

    summary = ctx.op_once(0, _run)

    # Record affordance telemetry for every tool invocation in this attempt.
    if ctx.affordances is not None and ctx.tools is not None:
        for inv in ctx.tools.invocations:
            ctx.affordances.record_tool(inv)
        for conflict in ctx.tools.scheduler.conflicts:
            ctx.affordances.record_conflict(conflict)
        ctx.affordances.save()

    spent = state.spent.model_copy(update={"attempts": state.spent.attempts + 1})
    if ctx.model is not None:
        spent = spent.model_copy(
            update={
                "tokens": state.spent.tokens + ctx.model.spend.tokens,
                "cost_usd": state.spent.cost_usd + ctx.model.spend.cost_usd,
                "tool_calls": state.spent.tool_calls + int(summary["tool_invocations"]),
            }
        )
    elif ctx.tools is not None:
        spent = spent.model_copy(
            update={"tool_calls": state.spent.tool_calls + int(summary["tool_invocations"])}
        )

    from contracts.resources import ResourceConflict
    from contracts.run import StepWave

    waves = [StepWave.model_validate(w) for w in summary["waves"]]
    conflicts = [ResourceConflict.model_validate(c) for c in summary["conflicts"]]

    if not summary["ok"]:
        detail = summary["error"] or "skill application failed"
        if summary["merge_timeout"]:
            detail = f"claim timeout: {detail}"
        signal = FailureSignal(source="solver", detail=detail, at=now())
        new_state = state.model_copy(
            update={
                "attempt_no": attempt_no,
                "spent": spent,
                "failure_signal": signal,
                "transcript_ref": summary["transcript_ref"],
                "step_waves": [*state.step_waves, *waves],
                "resource_conflicts": [*state.resource_conflicts, *conflicts],
            }
        )
        return NodeOutcome(
            state=new_state,
            route="pre_validation_failure_signal",
            note=f"applicator failed: {detail}",
        )

    new_state = state.model_copy(
        update={
            "attempt_no": attempt_no,
            "spent": spent,
            "transcript_ref": summary["transcript_ref"],
            "artifacts": [
                *state.artifacts,
                Artifact(
                    kind="text",
                    ref=summary["transcript_ref"] or f"{ctx.run_id}/attempt-{attempt_no}",
                    description="structured attempt transcript",
                ),
            ],
            "step_waves": [*state.step_waves, *waves],
            "failure_signal": None,
        }
    )
    return NodeOutcome(state=new_state, route="attempt_completed")


def _solve_script_via_tools(
    state: RunState, ctx: NodeContext, attempt_no: int, script: list[str]
) -> NodeOutcome:
    assert ctx.tools is not None
    writer = (
        TranscriptWriter(ctx.transcripts, ctx.run_id, attempt_no)
        if ctx.transcripts is not None
        else None
    )
    for op_seq, command in enumerate(script):
        requested = BudgetReservation(tool_calls=op_seq + 1)
        exhausted = budget_excess(state.budget, state.spent, state.reserved, requested)
        if exhausted is not None:
            signal = FailureSignal(
                source="solver",
                detail=f"budget exhausted before tool dispatch: {exhausted}",
                at=now(),
                class_hint="budget",
            )
            return NodeOutcome(
                state=state.model_copy(update={"failure_signal": signal}),
                route="pre_validation_failure_signal",
                note=f"tool-call budget exhausted: {exhausted}",
            )
        def _run(cmd: str = command, seq: int = op_seq) -> dict:
            if writer:
                writer.event("tool", tool="shell", command=cmd)
            result = ctx.tools.invoke(  # type: ignore[union-attr]
                "shell", {"command": cmd}, workdir=ctx.workdir, step_id=f"script-{seq}"
            )
            if ctx.affordances is not None:
                ctx.affordances.record_tool(result)
                ctx.affordances.save()
            return {
                "returncode": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "flaky": ctx.tools.is_flaky("shell") if ctx.tools else False,
            }

        result = ctx.op_once(op_seq, _run)
        if result["returncode"] != 0:
            detail = f"step {op_seq} exited {result['returncode']}: {command}"
            if result.get("flaky"):
                detail = f"flaky tool=shell: {detail}"
            signal = FailureSignal(source="solver", detail=detail, at=now())
            # Charge every tool call attempted so far (0..op_seq inclusive), not only attempts.
            new_state = state.model_copy(
                update={
                    "attempt_no": attempt_no,
                    "spent": state.spent.model_copy(
                        update={
                            "attempts": state.spent.attempts + 1,
                            "tool_calls": state.spent.tool_calls + op_seq + 1,
                        }
                    ),
                    "failure_signal": signal,
                    "transcript_ref": writer.finalize() if writer else None,
                }
            )
            return NodeOutcome(
                state=new_state,
                route="pre_validation_failure_signal",
                note=f"solver-raised failure signal at step {op_seq}",
            )

    transcript_ref = writer.finalize() if writer else f"{ctx.run_id}/attempt-{attempt_no}"
    new_state = state.model_copy(
        update={
            "attempt_no": attempt_no,
            "spent": state.spent.model_copy(
                update={
                    "attempts": state.spent.attempts + 1,
                    "tool_calls": state.spent.tool_calls + len(script),
                }
            ),
            "transcript_ref": transcript_ref,
            "artifacts": [
                *state.artifacts,
                Artifact(kind="text", ref=transcript_ref, description="scripted attempt transcript"),
            ],
            "failure_signal": None,
        }
    )
    return NodeOutcome(state=new_state, route="attempt_completed")


def _solve_legacy_script(
    state: RunState, ctx: NodeContext, attempt_no: int, script: list[str]
) -> NodeOutcome:
    for op_seq, command in enumerate(script):
        result = ctx.op_once(op_seq, functools.partial(_run_command, command, ctx))
        if result["returncode"] != 0:
            signal = FailureSignal(
                source="solver",
                detail=f"step {op_seq} exited {result['returncode']}: {command}",
                at=now(),
            )
            new_state = state.model_copy(
                update={
                    "attempt_no": attempt_no,
                    "spent": state.spent.model_copy(update={"attempts": state.spent.attempts + 1}),
                    "failure_signal": signal,
                }
            )
            return NodeOutcome(
                state=new_state,
                route="pre_validation_failure_signal",
                note=f"solver-raised failure signal at step {op_seq}",
            )

    transcript_ref = f"{ctx.run_id}/attempt-{attempt_no}"
    new_state = state.model_copy(
        update={
            "attempt_no": attempt_no,
            "spent": state.spent.model_copy(update={"attempts": state.spent.attempts + 1}),
            "transcript_ref": transcript_ref,
            "artifacts": [
                *state.artifacts,
                Artifact(kind="text", ref=transcript_ref, description="scripted attempt transcript"),
            ],
            "failure_signal": None,
        }
    )
    return NodeOutcome(state=new_state, route="attempt_completed")


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
    tool_calls = 0
    cost = 0.0
    tokens = 0
    last_error: str | None = None
    max_steps = _scratch_max_steps()

    for step in range(max_steps):
        requested = BudgetReservation(tool_calls=tool_calls + 1)
        exhausted = budget_excess(state.budget, state.spent, state.reserved, requested)
        if exhausted is not None:
            signal = FailureSignal(
                source="solver",
                detail=f"budget exhausted before tool dispatch: {exhausted}",
                at=now(),
                class_hint="budget",
            )
            return NodeOutcome(
                state=state.model_copy(
                    update={
                        "attempt_no": attempt_no,
                        "spent": state.spent.model_copy(
                            update={
                                "attempts": state.spent.attempts + 1,
                                "tool_calls": state.spent.tool_calls + tool_calls,
                                "cost_usd": state.spent.cost_usd + cost,
                                "tokens": state.spent.tokens + tokens,
                            }
                        ),
                        "failure_signal": signal,
                        "transcript_ref": writer.finalize() if writer else None,
                    }
                ),
                route="pre_validation_failure_signal",
                note=f"scratch budget exhausted: {exhausted}",
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
            signal = FailureSignal(
                source="solver",
                detail=f"environment: model error during scratch: {exc}",
                at=now(),
                class_hint="environment",
            )
            return NodeOutcome(
                state=state.model_copy(
                    update={
                        "attempt_no": attempt_no,
                        "spent": state.spent.model_copy(
                            update={
                                "attempts": state.spent.attempts + 1,
                                "tool_calls": state.spent.tool_calls + tool_calls,
                                "cost_usd": state.spent.cost_usd + cost,
                                "tokens": state.spent.tokens + tokens,
                            }
                        ),
                        "failure_signal": signal,
                        "transcript_ref": writer.finalize() if writer else None,
                    }
                ),
                route="pre_validation_failure_signal",
                note="scratch model error",
            )
        cost += response.cost_usd
        tokens += response.prompt_tokens + response.completion_tokens
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

        def _run(cmd: str = command, seq: int = step) -> dict:
            if writer:
                writer.event("tool", tool="shell", command=cmd, step=seq)
            result = ctx.tools.invoke(  # type: ignore[union-attr]
                "shell", {"command": cmd}, workdir=ctx.workdir, step_id=f"scratch-{seq}"
            )
            if ctx.affordances is not None:
                ctx.affordances.record_tool(result)
                ctx.affordances.save()
            return {
                "returncode": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        result = ctx.op_once(step, _run)
        tool_calls += 1
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
        transcript_ref = writer.finalize() if writer else f"{ctx.run_id}/attempt-{attempt_no}"
        new_state = state.model_copy(
            update={
                "attempt_no": attempt_no,
                "spent": state.spent.model_copy(
                    update={
                        "attempts": state.spent.attempts + 1,
                        "tool_calls": state.spent.tool_calls + tool_calls,
                        "cost_usd": state.spent.cost_usd + cost,
                        "tokens": state.spent.tokens + tokens,
                    }
                ),
                "transcript_ref": transcript_ref,
                "artifacts": [
                    *state.artifacts,
                    Artifact(
                        kind="text",
                        ref=transcript_ref,
                        description="scratch observe-act transcript",
                    ),
                ],
                "failure_signal": None,
            }
        )
        return NodeOutcome(
            state=new_state,
            route="attempt_completed",
            note=f"scratch observe-act completed after {step + 1} step(s)",
        )

    signal = FailureSignal(
        source="solver",
        detail=last_error or f"scratch observe-act exhausted {max_steps} steps",
        at=now(),
    )
    return NodeOutcome(
        state=state.model_copy(
            update={
                "attempt_no": attempt_no,
                "spent": state.spent.model_copy(
                    update={
                        "attempts": state.spent.attempts + 1,
                        "tool_calls": state.spent.tool_calls + tool_calls,
                        "cost_usd": state.spent.cost_usd + cost,
                        "tokens": state.spent.tokens + tokens,
                    }
                ),
                "failure_signal": signal,
                "transcript_ref": writer.finalize() if writer else None,
            }
        ),
        route="pre_validation_failure_signal",
        note="scratch observe-act exhausted without success",
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
