"""Trajectory event stream (ADR-0011). Engine-owned; nodes never write here."""

from fandea.trajectory.emitter import TrajectoryEmitter
from fandea.trajectory.store import TrajectoryStore

__all__ = ["TrajectoryEmitter", "TrajectoryStore"]
