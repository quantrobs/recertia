"""Counterfactual replay (ADR-0011). Offline only; never import from fandea.nodes."""

from fandea.replay.harness import ReplayHarness
from fandea.replay.pack import build_replay_pack
from fandea.replay.sample import sample_trajectories_for_skill

__all__ = ["ReplayHarness", "build_replay_pack", "sample_trajectories_for_skill"]
