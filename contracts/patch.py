"""Practice-published patch template (ADR-0015).

User-facing ``evolve`` MAY apply a published template as the single class repair.
It MUST NOT search. Templates live on the improvement plane.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.failure import FailureClass


class PatchTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str
    failure_signature: str
    failure_class: FailureClass
    operations: list[dict[str, Any]] = Field(default_factory=list)
    published_from_job: str = "practice"
    content_hash: str
    published_at: datetime | None = None
