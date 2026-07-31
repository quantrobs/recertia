"""Shadow execution: offline comparison that never reaches the caller (M5)."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.stats import SkillStats, Trust
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
    """Update trust/contribution counters for a shadow skill; result is never caller-visible."""

    status = store.get_status(skill_id, version)
    if status.lifecycle not in ("shadow", "approved"):
        raise ValueError(f"shadow outcomes only for shadow/approved; got {status.lifecycle}")
    stats = store.get_stats(skill_id, version)
    apps = stats.trust.applications + 1
    succs = stats.trust.successes + (1 if success else 0)
    contrib_apps = stats.contribution.applications + 1
    contrib_succs = stats.contribution.successes + (1 if success else 0)
    store.write_stats(
        SkillStats(
            skill_id=skill_id,
            version=version,
            trust=Trust(applications=apps, successes=succs),
            contribution=stats.contribution.model_copy(
                update={"applications": contrib_apps, "successes": contrib_succs}
            ),
        )
    )
    return ShadowResult(skill_id=skill_id, version=version, success=success, visible_to_caller=False)


def enter_shadow(store: SkillStore, skill_id: str, version: int) -> None:
    status = store.get_status(skill_id, version)
    store.write_status(status.model_copy(update={"lifecycle": "shadow", "active": False}))
