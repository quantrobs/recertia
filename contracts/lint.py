"""Packaging lint report + content hash (ADR-0015 P0′).

Deterministic, no model. Store re-lints only when ``lint_content_hash`` disagrees
with the current bytes. Compose claim conflicts share the existing uses-DAG walk.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts.skill import SkillVersion

LintSeverity = Literal["error", "warning"]


class LintFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: LintSeverity
    message: str


class LintReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[LintFinding] = []
    content_hash: str | None = None

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == "error"]


def lint_content_hash(version: SkillVersion) -> str:
    """Stable hash of the lintable surface. Hygiene and distilled_at are excluded."""

    payload = version.model_dump(
        mode="json",
        exclude={
            "hygiene": True,
            "provenance": {"distilled_at"},
        },
    )
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
