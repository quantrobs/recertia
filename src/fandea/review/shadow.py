"""Shadow execution: offline comparison that never reaches the caller (M5)."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.stats import PredictiveTrust, SkillStats
from fandea.memory.procedural.store import SkillStore


@dataclass
class ShadowResult:
    skill_id: str
    version: int
    success: bool
    visible_to_caller: bool = False


def record_shadow_outcome(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    success: bool,
) -> ShadowResult:
    """Update predictive trust for an offline slot; result is never caller-visible."""

    status = store.get_status(skill_id, version)
    if status.lifecycle not in ("shadow", "approved", "benched"):
        raise ValueError(f"shadow outcomes only for shadow/approved/benched; got {status.lifecycle}")
    stats = store.get_stats(skill_id, version)
    apps = stats.predictive_trust.applications + 1
    succs = stats.predictive_trust.successes + (1 if success else 0)
    store.write_stats(
        SkillStats(
            skill_id=skill_id,
            version=version,
            predictive_trust=PredictiveTrust(applications=apps, successes=succs),
            contribution=stats.contribution,
        )
    )
    return ShadowResult(skill_id=skill_id, version=version, success=success, visible_to_caller=False)


def enter_shadow(store: SkillStore, skill_id: str, version: int) -> None:
    status = store.get_status(skill_id, version)
    store.write_status(status.model_copy(update={"lifecycle": "shadow", "active": False}))
