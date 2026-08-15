"""Scope levels and cross-scope promotion records (specs §15.4 / architecture §15.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["run", "project", "org", "global"]

SCOPE_ORDER: tuple[Scope, ...] = ("run", "project", "org", "global")


class RedactionReport(BaseModel):
    """What was stripped or rewritten when promoting across scopes."""

    model_config = ConfigDict(extra="forbid")

    fields_removed: list[str] = Field(default_factory=list)
    fields_rewritten: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ScopePromotion(BaseModel):
    """Audit record for a reviewed cross-scope promotion."""

    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["fact", "skill"]
    artifact_id: str
    from_scope: Scope
    to_scope: Scope
    reviewer: str = Field(min_length=1)
    redaction: RedactionReport
    promoted_at: datetime
    ledger_target: str | None = None


def scope_rank(scope: Scope) -> int:
    return SCOPE_ORDER.index(scope)


def is_upscope(from_scope: Scope, to_scope: Scope) -> bool:
    return scope_rank(to_scope) > scope_rank(from_scope)
