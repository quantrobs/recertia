"""Faithfulness intervention contracts (Zhao et al. 2026). Eval-only; never a production field."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.eval import CausalLiftResult

FaithfulnessIntervention = Literal["empty", "corrupt", "irrelevant", "filler"]

FAITHFULNESS_STRATEGY_PREFIX = "faithfulness:"


class TrajectoryDivergence(BaseModel):
    """Decision-level divergence between a baseline trajectory and an intervened one."""

    model_config = ConfigDict(extra="forbid")

    jaccard: float = Field(ge=0.0, le=1.0)
    edit_distance: int = Field(ge=0)
    event_count_baseline: int = Field(ge=0)
    event_count_intervened: int = Field(ge=0)


class FaithfulnessArmResult(BaseModel):
    """One intervention versus the unmodified retrieval baseline."""

    model_config = ConfigDict(extra="forbid")

    intervention: FaithfulnessIntervention
    strategy: str
    performance_delta: float | None = None
    lift: CausalLiftResult | None = None
    divergence: TrajectoryDivergence
    detectable_change: bool
    skill_used: bool = True


class FaithfulnessReport(BaseModel):
    """Fraction of interventions that moved success or the trajectory (faithfulness score)."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: int
    task_class: str
    snapshot_id: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    arms: list[FaithfulnessArmResult] = Field(default_factory=list)
    baseline_successes: int = Field(ge=0)
    baseline_trials: int = Field(ge=0)
    at: datetime
