"""Semantic-plane facts (specs §13.2). One assertion per record; contradictions are retained."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asserting_run: str | None = None
    asserting_job: str | None = None
    asserting_human: str | None = None
    evidence: str | None = None


class Fact(BaseModel):
    """Canonical fact under ``facts/<scope>/<slug>.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    fact_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    scope: Literal["run", "project", "org", "global"] = "project"
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    assertion: str = Field(min_length=5, max_length=2000)
    status: Literal["asserted", "verified", "contradicted", "demoted"] = "asserted"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    provenance: FactProvenance
    verified_at: datetime | None = None
    contradicts: list[str] = Field(default_factory=list)
    authored_at: datetime
