"""Live-mix admission: golden pass certifies a version; it does not steer live traffic.

Human-authored and mined skills may enter the active set on approval. ``self_distilled``
skills stay ``approved`` but inactive until contribution evidence shows they are not
hurting live-like traffic (shadow slots gather that evidence). Below the evidence floor
they are not blocked forever — they are also not put on the caller's critical path.
"""

from __future__ import annotations

from typing import Literal

from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus

LiveMixReason = Literal[
    "live",
    "shadow_trial",
    "negative_contribution",
    "capped",
    "benched",
    "needs_recert",
    "quarantined",
    "deprecated",
    "not_approved",
]


def live_mix_eligible(version: SkillVersion, stats: SkillStats | None) -> bool:
    """Whether an approved version may compete for an active retrieval slot."""

    if version.provenance.curation != "self_distilled":
        return True
    if stats is None:
        return False
    estimate = stats.contribution.estimate
    if estimate is None:
        return False
    return estimate >= 0.0


def live_mix_reason(
    version: SkillVersion,
    status: SkillStatus,
    stats: SkillStats | None,
    *,
    consecutive_field_failures: int = 0,
) -> LiveMixReason:
    """Operator-visible reason the version is or is not on the live mix."""

    _ = consecutive_field_failures
    if status.lifecycle == "quarantined":
        return "quarantined"
    if status.lifecycle == "needs_recert":
        return "needs_recert"
    if status.lifecycle == "benched":
        return "benched"
    if status.lifecycle == "deprecated":
        return "deprecated"
    if status.lifecycle != "approved":
        return "not_approved"
    if status.active:
        return "live"
    if version.provenance.curation == "self_distilled" and not live_mix_eligible(version, stats):
        estimate = None if stats is None else stats.contribution.estimate
        if estimate is not None and estimate < 0.0:
            return "negative_contribution"
        return "shadow_trial"
    return "capped"


def live_mix_view(
    version: SkillVersion,
    status: SkillStatus,
    stats: SkillStats | None,
    *,
    consecutive_field_failures: int = 0,
) -> dict[str, object]:
    """Console/API payload: active bit plus why."""

    return {
        "active": status.active,
        "eligible": live_mix_eligible(version, stats) if status.lifecycle == "approved" else False,
        "reason": live_mix_reason(
            version,
            status,
            stats,
            consecutive_field_failures=consecutive_field_failures,
        ),
        "curation": version.provenance.curation,
        "consecutive_field_failures": consecutive_field_failures,
    }
