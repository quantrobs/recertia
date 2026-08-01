"""Sample stored trajectories that referenced a skill (ADR-0011 Curator input)."""

from __future__ import annotations

from contracts.trajectory import Trajectory
from recertia.trajectory.store import TrajectoryStore


def sample_trajectories_for_skill(
    store: TrajectoryStore,
    *,
    skill_id: str,
    limit: int = 50,
) -> list[Trajectory]:
    """Return closed trajectories that mentioned ``skill_id`` in any event."""

    hits: list[Trajectory] = []
    for traj in store.iter_trajectories():
        if any(ev.skill_id == skill_id for ev in traj.events):
            hits.append(traj)
        if len(hits) >= limit:
            break
    return hits
