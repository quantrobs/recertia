"""``solve``: run a scripted tool sequence and produce a transcript (specs §4). M0 stub.

M0 has no model, no tool registry, and no skill to apply — "a scripted tool sequence" per the
implementation plan means the run's ``ctx.script`` (a fixed list of shell commands) stands in
for a skill's step graph. Every command is expected to succeed; an unexpected nonzero exit is
an environment/tool failure raised directly, before validation ever runs (ADR-0008) — that is
a different failure mode from "the steps ran fine but the result does not satisfy criteria",
which is ``validate``'s job to discover.
"""

from __future__ import annotations

import functools
import subprocess

from contracts.failure import FailureSignal
from contracts.run import Artifact, RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def solve(state: RunState, ctx: NodeContext) -> NodeOutcome:
    """Assumes ``state.workspace_snapshots`` already has the pristine attempt-0 snapshot.

    The orchestrator takes that snapshot as part of the transition *into* the first ``solve``
    call, before any subprocess runs — not here — so a crash partway through this node's script
    can never cause the "clean" snapshot to capture an already-mutated workspace.
    """

    attempt_no = state.attempt_no + 1
    script = ctx.script or ["true"]

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
                Artifact(kind="text", ref=transcript_ref, description="M0 scripted attempt transcript"),
            ],
            "failure_signal": None,
        }
    )
    return NodeOutcome(state=new_state, route="attempt_completed")


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
