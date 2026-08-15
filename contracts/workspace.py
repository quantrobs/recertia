"""Registered host workspaces for Pilot / API workdir binding (RW0).

See ``docs/specifications/registered-workspaces.md``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisteredWorkspace(BaseModel):
    """Allowlisted host directory a tenant may bind as a run workdir."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    host_root: str = Field(min_length=1, description="Absolute host path (Windows drive-letter)")
    enabled: bool = True
    created_at: datetime | None = None
    created_by: str = Field(min_length=1)
    notes: str | None = None
