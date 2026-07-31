"""``solve``: run a scripted tool sequence and produce a transcript (specs §4).

M0/M1: no model, no general tool registry. The script comes from, in order:

1. ``ctx.script`` if the caller supplied one (tests, golden runner override).
2. The chosen skill's shell steps, when ``strategy`` is ``apply`` or ``adapt`` and a store is
   available (M1).
3. ``["true"]`` — a no-op scratch attempt that still produces a transcript so ``validate`` runs.
"""

from __future__ import annotations

import functools
import subprocess

from contracts.failure import FailureSignal
from contracts.run import Artifact, RunState
from fandea.memory.procedural.apply import script_from_skill
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def solve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    """Assumes ``state.workspace_snapshots`` already has the pristine attempt-0 snapshot.

    The orchestrator takes that snapshot as part of the transition *into* the first ``solve``
    call, before any subprocess runs — not here — so a crash partway through this node's script
    can never cause the "clean" snapshot to capture an already-mutated workspace.
    """

    attempt_no = state.attempt_no + 1
    script = _resolve_script(state, ctx)

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
        return script_from_skill(version)
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
