"""``SkillStatus``: the append-only, projected-to-current half of ADR-0007's split.

Everything here changes after the version is written. It is never merged back onto
``SkillVersion``; it is a separate record keyed by the same ``(skill_id, version)``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from contracts.common import RETRIEVABLE_LIFECYCLES, Lifecycle


class Certification(BaseModel):
    """What environment and model this version was last validated against (specs §13).

    Lives on ``SkillStatus``, not ``SkillVersion``: a model upgrade can mark a version
    ``needs_recert`` with no new evidence collected about the version's content, which is a
    status fact, not an immutable property of the artifact.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_validated_on: str | None = None
    tool_fingerprint: dict[str, str] = {}
    golden_set_ref: str | None = None
    last_recertified_at: datetime | None = None
    recert_status: Literal["fresh", "stale", "failed", "never"] = "never"


class Retirement(BaseModel):
    """Benching record (ADR-0006). Reversible; history retained."""

    model_config = ConfigDict(extra="forbid")

    benched_at: datetime | None = None
    reason: Literal["negative_contribution", "cap_pressure", "superseded_child", "manual"] | None = (
        None
    )
    evidence: str | None = None
    restored_at: datetime | None = None
    grace_period_remaining: int | None = None


class SkillStatus(BaseModel):
    """Current projection of the append-only lifecycle event log for one ``(skill_id, version)``.

    Governance tier: T1 for ``lifecycle`` transitions (promotion-gated, per ADR-0005); T0 for
    ``active`` (recomputed by the Curator on every pass, per specs §24.1).
    """

    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: int
    lifecycle: Lifecycle = "draft"
    active: bool = False
    certification: Certification = Certification()
    retirement: Retirement = Retirement()

    @model_validator(mode="after")
    def _active_requires_retrievable_lifecycle(self) -> "SkillStatus":
        if self.active and self.lifecycle not in RETRIEVABLE_LIFECYCLES:
            raise ValueError(
                f"active=True requires lifecycle in {sorted(RETRIEVABLE_LIFECYCLES)}, "
                f"got {self.lifecycle!r} (specs §2.2, §24.1)"
            )
        return self

    @property
    def is_retrievable(self) -> bool:
        """Only ``approved`` **and** in the active set is eligible for direct application.

        ``shadow`` is retrievable for comparison only and MUST NOT affect the caller's result
        (specs §2.2) — that rule is enforced by the caller of this property, not here.
        """

        return self.lifecycle == "approved" and self.active
