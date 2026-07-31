"""Versioned T2 policy documents (specs §13.5, §25; references §1.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthoringPrior(BaseModel):
    """Rules the distiller must apply on every success or failure-cluster path."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    version: str = Field(min_length=1)
    require_parameter_or_recurrence: bool = True
    require_non_judge_criterion: bool = True
    require_sensitivity_proof: bool = True
    max_steps: int = Field(default=12, ge=1, le=50)
    prefer_shell_when_applicable: bool = True
    notes: list[str] = Field(default_factory=list)


class PolicyBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_max_attempts: int = Field(default=3, ge=1)
    default_max_cost_usd: float = Field(default=1.0, gt=0)
    ablation_rate: float = Field(default=0.1, ge=0.0, le=1.0)


class Policy(BaseModel):
    """Versioned T2 policy document: thresholds, budgets, and authoring prior pointer."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    version: str = Field(min_length=1)
    authoring_prior_version: str = Field(min_length=1)
    budgets: PolicyBudgets = Field(default_factory=PolicyBudgets)
    shadow_min_lift: float = Field(default=0.05, ge=0.0)
    evidence_floor: int = Field(default=30, ge=1)
    active_cap_per_task_class: int = Field(default=50, ge=1)
    require_tool_approval_for_non_read: bool = True
    notes: list[str] = Field(default_factory=list)
