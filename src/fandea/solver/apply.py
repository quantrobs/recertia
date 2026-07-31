"""Skill application: parameter binding, wave execution, claim scheduling (specs §26, M2)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from contracts.resources import ResourceClaim, ResourceConflict
from contracts.run import StepWave
from contracts.skill import SkillVersion, Step
from fandea.solver.tools import ClaimScheduler, ClaimTimeoutError, ToolResult, ToolRuntime
from fandea.solver.transcript import TranscriptWriter
from fandea.workspace import WorkspaceManager

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


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


def bind_parameters(template: str, params: dict[str, object]) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        return str(params[name])

    return _PLACEHOLDER.sub(repl, template)


def bind_inputs(inputs: dict, params: dict[str, object]) -> dict:
    out: dict = {}
    for k, v in inputs.items():
        if isinstance(v, str):
            out[k] = bind_parameters(v, params)
        else:
            out[k] = v
    return out


def topological_waves(steps: list[Step], max_parallel: int) -> list[list[Step]]:
    """Compute dependency waves ignoring claims (claims are resolved at dispatch time)."""

    remaining = {s.id: s for s in steps}
    done: set[str] = set()
    waves: list[list[Step]] = []
    while remaining:
        ready = [
            s
            for s in remaining.values()
            if all(d in done for d in s.depends_on)
        ]
        if not ready:
            raise ValueError("step graph has a cycle or unsatisfied depends_on at runtime")
        # Claim-aware packing happens in the applicator; here we just batch by dependency.
        wave = ready[:max_parallel]
        waves.append(wave)
        for s in wave:
            done.add(s.id)
            del remaining[s.id]
    return waves


def claims_conflict(a: list[ResourceClaim], b: list[ResourceClaim]) -> bool:
    for ca in a:
        for cb in b:
            if ClaimScheduler.conflicts_with(ca, cb):
                return True
    return False


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
        wave_idx = 0
        snap_run = snapshots_run_id or run_id

        while remaining:
            ready = [
                s
                for s in remaining.values()
                if all(d in done for d in s.depends_on)
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
            inputs = bind_inputs(step.inputs, params)
            # Bound loops: execute until success or max_iterations.
            max_iter = step.loop.max_iterations if step.loop else 1
            last: ToolResult | None = None
            err: str | None = None
            for _ in range(max_iter):
                transcript.event("step_start", step_id=step.id, tool=tool_name, inputs=inputs)
                try:
                    last = self.runtime.invoke(
                        tool_name,
                        inputs,
                        workdir=workdir,
                        step_id=step.id,
                        extra_claims=list(step.resources),
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
