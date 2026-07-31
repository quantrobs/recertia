"""Versioned authoring prior (T2 document; specs §25, references §1.3)."""

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
