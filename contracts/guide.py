"""Ephemeral execution guide emitted by ``plan`` (ADR-0015).

Deterministic stitch only. Never stored as a skill. Distill may log that a guide
existed; it MUST NOT copy guide strings into ``SkillVersion``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExecutionGuide(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: list[str] = []
    checks: list[str] = []
    avoid: list[str] = []
    fallback: list[str] = []
    source_skills: list[tuple[str, int]] = []
    adapted_at: datetime
    method: Literal["deterministic_stitch"] = "deterministic_stitch"
