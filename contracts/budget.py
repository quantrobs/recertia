"""Budget and spend, shared by ``RunState`` and ``Branch`` (specs §10.1, §18)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=4, ge=1)
    max_tool_calls: int = Field(default=200, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_wall_clock_s: int = Field(default=900, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_branches: int = Field(default=3, ge=1, le=3)
    max_parallel_steps: int = Field(default=8, ge=1)
    claim_timeout_s: int = Field(default=60, ge=1)
    max_versions_written: int = Field(default=2, ge=0)


class Spend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempts: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    wall_clock_s: float = Field(default=0.0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    versions_written: int = Field(default=0, ge=0)
