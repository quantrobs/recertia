"""Review-queue decisions for distilled skill drafts (specs §4, §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    skill_id: str
    version: int
    run_id: str
    outcome: Literal["approved", "rejected", "changes_requested"]
    reviewer: str
    note: str | None = None
    golden_report_ref: str | None = None
    decided_at: datetime
    policy: str = Field(default="human_default")
