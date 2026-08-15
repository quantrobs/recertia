"""Offline counterfactual replay harness (ADR-0011). Retrieval-only first."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.replay import ReplayObservation, ReplayRequest, WorldState
from contracts.trajectory import Trajectory
from recertia.trajectory.store import TrajectoryStore


class ReplayHarness:
    """Replay a trajectory under a candidate :class:`WorldState`.

    ``retrieval_only`` compares original plan_choice skill against what the
    world would suppress — no solver calls.
    """

    def __init__(self, store: TrajectoryStore) -> None:
        self.store = store

    def replay(self, request: ReplayRequest) -> ReplayObservation:
        traj = self.store.get_trajectory(request.trajectory_ref)
        if traj is None:
            return ReplayObservation(
                run_id=request.trajectory_ref,
                mode=request.mode,
                status="failed",
                reason="trajectory not found",
                at=datetime.now(timezone.utc),
            )
        if request.mode == "retrieval_only":
            return self._retrieval_only(traj, request.world)
        if request.mode == "validate_only":
            return self._validate_only(traj)
        return ReplayObservation(
            run_id=traj.run_id,
            mode=request.mode,
            status="skipped",
            reason="full_execution requires RECERTIA_ALLOW_FULL_REPLAY=1 and orchestrator_factory",
            at=datetime.now(timezone.utc),
        )

    def _retrieval_only(self, traj: Trajectory, world: WorldState) -> ReplayObservation:
        plan = next((e for e in traj.events if e.event_kind == "plan_choice"), None)
        original_skill = plan.skill_id if plan else None
        suppressed = set(world.suppressed_skill_ids)
        for key, lifecycle in world.skill_status_overrides.items():
            if lifecycle in {"benched", "quarantined", "deprecated", "retired"}:
                sid = key.split("@", 1)[0]
                suppressed.add(sid)
        counterfactual_skill = None if (original_skill in suppressed) else original_skill
        plan_would_change = original_skill != counterfactual_skill
        # Original first-attempt success from terminal + attempt metadata.
        terminal = next((e for e in traj.events if e.event_kind == "terminal"), None)
        original_ok = bool(
            terminal
            and terminal.payload_inline
            and terminal.payload_inline.get("terminal") == "solved"
            and terminal.payload_inline.get("attempt_no") == 1
        )
        # Conservative counterfactual: if plan would change, treat as unknown/fail for pack.
        cf_ok = original_ok if not plan_would_change else False
        return ReplayObservation(
            run_id=traj.run_id,
            mode="retrieval_only",
            original_first_attempt_success=original_ok,
            counterfactual_first_attempt_success=cf_ok,
            original_skill_id=original_skill,
            counterfactual_skill_id=counterfactual_skill,
            plan_would_change=plan_would_change,
            status="completed",
            at=datetime.now(timezone.utc),
        )

    def _validate_only(self, traj: Trajectory) -> ReplayObservation:
        scored = [e for e in traj.events if e.event_kind == "criterion_scored"]
        if not scored:
            return ReplayObservation(
                run_id=traj.run_id,
                mode="validate_only",
                status="skipped",
                reason="no criterion_scored events",
                at=datetime.now(timezone.utc),
            )
        passed = all(
            (e.payload_inline or {}).get("passed") for e in scored if e.payload_inline is not None
        )
        return ReplayObservation(
            run_id=traj.run_id,
            mode="validate_only",
            original_first_attempt_success=passed,
            counterfactual_first_attempt_success=passed,
            criterion_deltas=[
                {
                    "criterion_id": e.criterion_id,
                    "passed": (e.payload_inline or {}).get("passed"),
                }
                for e in scored
            ],
            status="completed",
            at=datetime.now(timezone.utc),
        )
