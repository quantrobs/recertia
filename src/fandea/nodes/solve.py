"""``solve``: apply a skill (or scratch) via the tool runtime and write a transcript (M2).

Fallback order:
1. Explicit ``ctx.script`` (tests / golden override) — still recorded into a transcript.
2. ``apply``/``adapt`` with a chosen skill + ``SkillApplicator`` (wave-based tool execution).
3. ``scratch`` via the model client proposing a shell command, executed through the tool runtime.
4. Legacy ``["true"]`` no-op when no M2 services are configured (M0/M1 tests).
"""

from __future__ import annotations

import functools
import subprocess

from contracts.failure import FailureSignal
from contracts.run import Artifact, RunState
from fandea.memory.procedural.apply import script_from_skill
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome
from fandea.solver.transcript import TranscriptWriter


def solve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    attempt_no = state.attempt_no + 1

    # M6: when fan_out left dispatched branches, execute each branch workspace once.
    if state.branches and any(b.status == "dispatched" for b in state.branches):
        return _solve_branches(state, ctx, attempt_no)

    if ctx.applicator is not None and state.strategy in ("apply", "adapt") and state.chosen and ctx.store:
        return _solve_via_applicator(state, ctx, attempt_no)

    script = _resolve_script(state, ctx)
    if ctx.transcripts is not None and ctx.tools is not None:
        return _solve_script_via_tools(state, ctx, attempt_no, script)

    return _solve_legacy_script(state, ctx, attempt_no, script)


def _solve_branches(state: RunState, ctx: NodeContext, attempt_no: int) -> NodeOutcome:
    import subprocess

    from contracts.criteria import CriterionResult

    updated = []
    total_cost = 0.0
    for branch in state.branches:
        if branch.status not in ("dispatched", "running"):
            updated.append(branch)
            continue
        work = ctx.workdir / branch.branch_id
        work.mkdir(parents=True, exist_ok=True)
        script = ctx.script or ["true"]
        ok = True
        for command in script:
            proc = subprocess.run(
                command, shell=True, cwd=work, capture_output=True, text=True, timeout=60
            )
            if proc.returncode != 0:
                ok = False
                break
        # Score owned criteria or a default true.
        results = [
            CriterionResult(criterion_id="branch-ok", kind="command", passed=ok, weight=1.0)
        ]
        cost = 0.01 * (1 + len(script))
        total_cost += cost
        updated.append(
            branch.model_copy(
                update={
                    "status": "succeeded" if ok else "failed",
                    "results": results,
                    "cost_usd": cost,
                    "workspace_ref": str(work),
                }
            )
        )

    # Parent budget must not exceed: if sum of child max would exceed, still record spent.
    spent = state.spent.model_copy(
        update={
            "attempts": state.spent.attempts + 1,
            "cost_usd": state.spent.cost_usd + total_cost,
        }
    )
    if state.budget.max_cost_usd is not None and spent.cost_usd > state.budget.max_cost_usd:
        from contracts.failure import FailureSignal
        from fandea.nodes._util import now

        signal = FailureSignal(source="solver", detail="parent budget exceeded by branches", at=now())
        new_state = state.model_copy(
            update={
                "attempt_no": attempt_no,
                "spent": spent,
                "branches": updated,
                "failure_signal": signal,
                "transcript_ref": f"{ctx.run_id}/branches-{attempt_no}",
            }
        )
        return NodeOutcome(state=new_state, route="pre_validation_failure_signal", note="budget exceeded")

    new_state = state.model_copy(
        update={
            "attempt_no": attempt_no,
            "spent": spent,
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
        from fandea.solver.transcript import TranscriptStore

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
                "flaky": ctx.tools.registry.is_flaky("shell") if ctx.tools else False,  # type: ignore[union-attr]
            }

        result = ctx.op_once(op_seq, _run)
        if result["returncode"] != 0:
            detail = f"step {op_seq} exited {result['returncode']}: {command}"
            if result.get("flaky"):
                detail = f"flaky tool=shell: {detail}"
            signal = FailureSignal(source="solver", detail=detail, at=now())
            new_state = state.model_copy(
                update={
                    "attempt_no": attempt_no,
                    "spent": state.spent.model_copy(update={"attempts": state.spent.attempts + 1}),
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


def _resolve_script(state: RunState, ctx: NodeContext) -> list[str]:
    if ctx.script is not None:
        return ctx.script
    if state.strategy in ("apply", "adapt") and state.chosen is not None and ctx.store is not None:
        version = ctx.store.get_version(state.chosen.skill_id, state.chosen.version)
        params = dict(state.chosen.bound_parameters)
        for p in version.parameters:
            if p.name not in params and p.default is not None:
                params[p.name] = p.default
        from fandea.solver.apply import bind_parameters

        raw = script_from_skill(version)
        return [bind_parameters(cmd, params) for cmd in raw]
    if state.strategy == "scratch" and ctx.model is not None:
        response = ctx.model.complete(
            f"Propose a single shell command to: {state.task.request}\n"
            "Reply with only the command, no markdown."
        )
        return [response.text.strip().splitlines()[0]]
    return ["true"]


def _run_command(command: str, ctx: NodeContext) -> dict:
    proc = subprocess.run(
        command,
        shell=True,
        cwd=ctx.workdir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
