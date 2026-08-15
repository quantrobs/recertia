"""Node output and checkpoint envelope contracts (S7 / specs §4–§5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.run import RunState


class NodeOutput(BaseModel):
    """Normative node return shape (specs §4); runtime ``NodeOutcome`` mirrors this."""

    model_config = ConfigDict(extra="forbid")

    state: RunState
    route: str | None = None
    note: str | None = None


class CheckpointRecord(BaseModel):
    """Persisted checkpoint envelope around a ``RunState`` snapshot (specs §5.3)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    seq: int = Field(ge=0)
    node: str
    next_node: str | None = None
    state: RunState
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
