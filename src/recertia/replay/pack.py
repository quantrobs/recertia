"""Build Curator-facing ReplayPack aggregates (ADR-0011)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from contracts.eval import BinomialSample
from contracts.replay import (
    ReplayMode,
    ReplayObservation,
    ReplayPack,
    ReplayRequest,
    WorldState,
)
from contracts.trajectory import Trajectory
from recertia.evals.statistics import causal_lift
from recertia.replay.harness import ReplayHarness
from recertia.trajectory.store import TrajectoryStore


def build_replay_pack(
    store: TrajectoryStore,
    *,
    trajectories: list[Trajectory],
    world: WorldState,
    mode: ReplayMode = "retrieval_only",
    purpose: str = "curator_counterfactual",
) -> ReplayPack:
    """Replay each trajectory under ``world`` and aggregate a lift-style pack."""

    harness = ReplayHarness(store)
    observations: list[ReplayObservation] = []
    for traj in trajectories:
        obs = harness.replay(
            ReplayRequest(trajectory_ref=traj.run_id, mode=mode, world=world)
        )
        observations.append(obs)

    treat_ok = sum(1 for o in observations if o.original_first_attempt_success)
    treat_n = sum(1 for o in observations if o.original_first_attempt_success is not None)
    cf_ok = sum(1 for o in observations if o.counterfactual_first_attempt_success)
    cf_n = sum(1 for o in observations if o.counterfactual_first_attempt_success is not None)
    lift = causal_lift(
        BinomialSample(successes=treat_ok, trials=treat_n),
        BinomialSample(successes=cf_ok, trials=cf_n),
        task_class="replay",
    )
    return ReplayPack(
        pack_id=uuid4().hex[:12],
        purpose=purpose,
        world=world,
        mode=mode,
        observations=observations,
        treatment_successes=treat_ok,
        treatment_trials=treat_n,
        counterfactual_successes=cf_ok,
        counterfactual_trials=cf_n,
        estimate=lift.estimate,
        interval=lift.interval,
        status=lift.status,
        created_at=datetime.now(timezone.utc),
    )
