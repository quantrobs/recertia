"""Eval / measurement contracts (specs §11, §19, §23)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float
    high: float
    level: float = Field(default=0.95, ge=0.0, le=1.0)
    method: str = "newcombe_wilson"


class BinomialSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successes: int = Field(ge=0)
    trials: int = Field(ge=0)

    @property
    def rate(self) -> float | None:
        if self.trials == 0:
            return None
        return self.successes / self.trials


LiftStatus = Literal[
    "established_positive",
    "established_negative",
    "not_established",
    "insufficient_data",
]


class CausalLiftResult(BaseModel):
    """Treatment − control first-attempt success with a difference CI (specs §19)."""

    model_config = ConfigDict(extra="forbid")

    task_class: str
    treatment: BinomialSample
    control: BinomialSample
    estimate: float | None
    interval: ConfidenceInterval | None
    status: LiftStatus
    snapshot_id: str | None = None
    model_version: str | None = None
    window: str | None = None

    def render_status(self) -> str:
        if self.status == "not_established":
            return "not established"
        if self.status == "insufficient_data":
            return "insufficient data"
        if self.status == "established_positive":
            return "established positive"
        return "established negative"


class ControlBaseline(BaseModel):
    """Persisted per-task-class control-arm baseline (specs §24.2; M5 contribution input)."""

    model_config = ConfigDict(extra="forbid")

    task_class: str
    snapshot_id: str
    model_version: str | None = None
    control: BinomialSample
    interval: ConfidenceInterval | None = None
    created_at: datetime
    report_id: str | None = None


class EvalObservation(BaseModel):
    """One run observation keyed for aggregation under a library snapshot."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_class: str
    arm: Literal["treatment", "control", "shadow", "practice"] = "treatment"
    snapshot_id: str
    model_version: str | None = None
    first_attempt_success: bool
    predicted_success: float | None = None
    terminal: str | None = None
    fixture_id: str | None = None
    is_eval_fixture: bool = False
    recorded_at: datetime


class MetricReport(BaseModel):
    """Aggregate §11 / §23 metrics for one snapshot window."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    model_version: str | None = None
    task_class: str | None = None
    reuse_rate: float | None = None
    first_attempt_success: float | None = None
    attempts_to_success: float | None = None
    cost_per_solved_task: float | None = None
    regression_rate: float | None = None
    causal_lift: CausalLiftResult | None = None
    calibration_error: float | None = None
    abstention_precision: float | None = None
    merge_gap_rate: float | None = None
    parallel_speedup: float | None = None
    fake_edge_rate: float | None = None
    judge_isolation_violations: int = 0
    unavailable: dict[str, str] = Field(default_factory=dict)
    at: datetime
