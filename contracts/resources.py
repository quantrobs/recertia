"""Resource claims shared by skill steps and fan-out branches (specs §26.2)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from contracts.common import ResourceKind, ResourceMode


class ResourceClaim(BaseModel):
    """A declared claim on something shared outside the workspace.

    Two units conflict when they claim the same ``id`` and at least one ``mode`` is ``write``
    or ``exclusive`` — whether or not an ``input_bindings``-derived dependency exists between them.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ResourceKind
    id: str
    mode: ResourceMode


class ResourceConflict(BaseModel):
    """One recorded wait on a claimed resource (specs §26.2)."""

    model_config = ConfigDict(extra="forbid")

    claim: ResourceClaim
    waiting: str
    holder: str
    waited_ms: int
    resolution: str = "acquired"  # "acquired" | "timed_out" | "deadlock_serialised"
