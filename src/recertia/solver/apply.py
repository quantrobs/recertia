"""Skill application: wave execution and claim scheduling (specs §26, M2).

Binding helpers live in :mod:`recertia.solver.bindings` and are re-exported here for
compatibility with ``from recertia.solver.apply import bind_inputs`` / ``bind_parameters``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from contracts.resources import ResourceClaim, ResourceConflict
from contracts.run import StepWave
from contracts.skill import SkillVersion, Step, StepOutput, step_dependencies
from recertia.solver.bindings import (
    bind_inputs,
    bind_parameters,
    claims_conflict,
    topological_waves,
)
from recertia.solver.runtime import StepInvokeContext
from recertia.solver.tools import ClaimTimeoutError, ToolResult, ToolRuntime
from recertia.solver.transcript import TranscriptWriter
from recertia.workspace import WorkspaceManager

__all__ = [
    "ApplyResult",
    "SkillApplicator",
    "StepOutcome",
    "WaveResult",
    "bind_inputs",
    "bind_parameters",
    "claims_conflict",
    "topological_waves",
]


@dataclass
class StepOutcome:
    step_id: str
    tool: str | None
    result: ToolResult | None
    skipped: bool = False
    error: str | None = None


@dataclass
class WaveResult:
    wave: StepWave
    outcomes: list[StepOutcome] = field(default_factory=list)
    conflicts: list[ResourceConflict] = field(default_factory=list)
    timed_out: bool = False
    serialised_retry: bool = False


@dataclass
class ApplyResult:
    ok: bool
    waves: list[WaveResult] = field(default_factory=list)
    outcomes: list[StepOutcome] = field(default_factory=list)
    transcript_ref: str | None = None
    error: str | None = None
    merge_timeout: bool = False
    """True when a claim timeout forced a serial re-run signal (failure class ``merge``)."""


class SkillApplicator:
    """Execute a skill's step DAG as claim-aware waves against a ToolRuntime."""

    def __init__(
        self,
        runtime: ToolRuntime,
        workspaces: WorkspaceManager,
        *,
        max_parallel_steps: int = 8,
        claim_timeout_s: float = 60.0,
    ) -> None:
        self.runtime = runtime
        self.workspaces = workspaces
        self.max_parallel_steps = max_parallel_steps
        # Ensure scheduler uses the configured timeout.
        self.runtime.scheduler.claim_timeout_s = claim_timeout_s

    def apply(
        self,
        version: SkillVersion,
        *,
        params: dict[str, object],
        workdir: Path,
        run_id: str,
        attempt_no: int,
        transcript: TranscriptWriter,
        snapshots_run_id: str | None = None,
    ) -> ApplyResult:
        steps = list(version.steps)
        done: set[str] = set()
        remaining = {s.id: s for s in steps}
        waves_out: list[WaveResult] = []
        all_outcomes: list[StepOutcome] = []
        step_outputs: dict[tuple[str, str], object] = {}
        wave_idx = 0
        snap_run = snapshots_run_id or run_id

        while remaining:
            ready = [
                s
                for s in remaining.values()
                if all(d in done for d in step_dependencies(s))
            ]
            if not ready:
                return ApplyResult(
                    ok=False,
                    waves=waves_out,
                    outcomes=all_outcomes,
                    error="unsatisfiable step dependencies at runtime",
                )

            # Pack a wave: greedy by declaration order, skipping claim conflicts with
            # already-selected members, capped at max_parallel_steps.
            selected: list[Step] = []
            selected_claims: list[list[ResourceClaim]] = []
            for step in ready:
                if len(selected) >= self.max_parallel_steps:
                    break
                step_claims = list(step.resources)
                if any(claims_conflict(step_claims, sc) for sc in selected_claims):
                    continue
                selected.append(step)
                selected_claims.append(step_claims)

            if not selected:
                # Every ready step conflicts with every other — take the first alone.
                selected = [ready[0]]

            snap_ref = self.workspaces.snapshot(workdir, snap_run, attempt_no=1000 + wave_idx)
            transcript.event(
                "wave_start",
                wave=wave_idx,
                step_ids=[s.id for s in selected],
                snapshot_ref=snap_ref,
            )

            wave_result = self._run_wave(
                selected,
                params=params,
                workdir=workdir,
                wave_idx=wave_idx,
                attempt_no=attempt_no,
                snapshot_ref=snap_ref,
                transcript=transcript,
                step_outputs=step_outputs,
            )
            waves_out.append(wave_result)
            all_outcomes.extend(wave_result.outcomes)

            if wave_result.timed_out:
                # Restore whole wave and re-run serially (specs §26.2).
                self.workspaces.restore(workdir, snap_ref)
                transcript.event("wave_serialise", wave=wave_idx, reason="claim_timeout")
                serial = self._run_wave(
                    selected,
                    params=params,
                    workdir=workdir,
                    wave_idx=wave_idx,
                    attempt_no=attempt_no,
                    snapshot_ref=snap_ref,
                    transcript=transcript,
                    step_outputs=step_outputs,
                    force_serial=True,
                )
                serial.serialised_retry = True
                waves_out.append(serial)
                all_outcomes.extend(serial.outcomes)
                if not all(o.result and o.result.ok for o in serial.outcomes if not o.skipped):
                    return ApplyResult(
                        ok=False,
                        waves=waves_out,
                        outcomes=all_outcomes,
                        transcript_ref=transcript.finalize(),
                        error="serialised wave still failed after claim timeout",
                        merge_timeout=True,
                    )
                for o in serial.outcomes:
                    self._record_outputs(
                        remaining[o.step_id], o, step_outputs, transcript
                    )
                    done.add(o.step_id)
                    remaining.pop(o.step_id, None)
                wave_idx += 1
                continue

            failed = [o for o in wave_result.outcomes if not o.skipped and not (o.result and o.result.ok)]
            if failed:
                # Rollback the whole wave (specs §17 / §26.1).
                self.workspaces.restore(workdir, snap_ref)
                transcript.event(
                    "wave_rollback",
                    wave=wave_idx,
                    failed=[o.step_id for o in failed],
                    snapshot_ref=snap_ref,
                )
                return ApplyResult(
                    ok=False,
                    waves=waves_out,
                    outcomes=all_outcomes,
                    transcript_ref=transcript.finalize(),
                    error=f"wave {wave_idx} failed: {[o.step_id for o in failed]}",
                )

            for o in wave_result.outcomes:
                self._record_outputs(remaining[o.step_id], o, step_outputs, transcript)
                done.add(o.step_id)
                remaining.pop(o.step_id, None)
            wave_idx += 1

        ref = transcript.finalize()
        return ApplyResult(ok=True, waves=waves_out, outcomes=all_outcomes, transcript_ref=ref)

    def _run_wave(
        self,
        steps: list[Step],
        *,
        params: dict[str, object],
        workdir: Path,
        wave_idx: int,
        attempt_no: int,
        snapshot_ref: str,
        transcript: TranscriptWriter,
        step_outputs: dict[tuple[str, str], object],
        force_serial: bool = False,
    ) -> WaveResult:
        step_ids = [s.id for s in steps]
        wave = StepWave(
            wave=wave_idx,
            step_ids=step_ids,
            attempt_no=attempt_no,
            snapshot_ref=snapshot_ref,
        )
        outcomes: list[StepOutcome] = []
        conflicts: list[ResourceConflict] = []

        def run_one(step: Step) -> StepOutcome:
            tool_name = step.tool or "shell"
            try:
                inputs = bind_inputs(step.inputs, params, step.input_bindings, step_outputs)
            except ValueError as exc:
                return StepOutcome(step_id=step.id, tool=tool_name, result=None, error=str(exc))
            step_context = StepInvokeContext(
                intent=bind_parameters(step.intent, params),
                params=dict(params),
            )
            # Bound loops: execute until success or max_iterations.
            max_iter = step.loop.max_iterations if step.loop else 1
            last: ToolResult | None = None
            err: str | None = None
            for _ in range(max_iter):
                transcript.event(
                    "step_start",
                    step_id=step.id,
                    tool=tool_name,
                    inputs=inputs,
                    input_bindings=[
                        {
                            "input": binding.input,
                            "source_step": binding.source_step,
                            "output": binding.output,
                        }
                        for binding in step.input_bindings
                    ],
                )
                try:
                    last = self.runtime.invoke(
                        tool_name,
                        inputs,
                        workdir=workdir,
                        step_id=step.id,
                        extra_claims=list(step.resources),
                        step_context=step_context,
                    )
                except ClaimTimeoutError as exc:
                    conflicts.append(exc.conflict)
                    transcript.event("step_claim_timeout", step_id=step.id, detail=str(exc))
                    return StepOutcome(
                        step_id=step.id, tool=tool_name, result=None, error=str(exc)
                    )
                transcript.event(
                    "step_end",
                    step_id=step.id,
                    ok=last.ok,
                    exit_code=last.exit_code,
                    duration_s=last.duration_s,
                )
                if last.ok:
                    break
                err = last.stderr or last.stdout
                if step.loop is None:
                    break
            return StepOutcome(step_id=step.id, tool=tool_name, result=last, error=err)

        timed_out = False
        if force_serial or len(steps) == 1:
            for step in steps:
                outcomes.append(run_one(step))
                if outcomes[-1].error and "claim timeout" in (outcomes[-1].error or ""):
                    timed_out = True
        else:
            with ThreadPoolExecutor(max_workers=len(steps)) as pool:
                futures = {pool.submit(run_one, s): s for s in steps}
                for fut in as_completed(futures):
                    outcome = fut.result()
                    outcomes.append(outcome)
                    if outcome.error and "claim timeout" in (outcome.error or ""):
                        timed_out = True

        # Preserve declaration order in outcomes.
        order = {s.id: i for i, s in enumerate(steps)}
        outcomes.sort(key=lambda o: order.get(o.step_id, 0))
        return WaveResult(
            wave=wave, outcomes=outcomes, conflicts=conflicts, timed_out=timed_out
        )

    @staticmethod
    def _record_outputs(
        step: Step,
        outcome: StepOutcome,
        step_outputs: dict[tuple[str, str], object],
        transcript: TranscriptWriter,
    ) -> None:
        if outcome.result is None or not outcome.result.ok:
            return
        for output in step.outputs:
            value = _output_value(output, outcome.result)
            step_outputs[(step.id, output.name)] = value
            transcript.event(
                "step_output",
                step_id=step.id,
                output=output.name,
                type=output.type,
                value=value,
            )


def _output_value(output: StepOutput, result: ToolResult) -> object:
    if output.value_from == "exit_code":
        return result.exit_code
    if output.value_from == "stderr":
        return result.stderr
    return result.stdout
