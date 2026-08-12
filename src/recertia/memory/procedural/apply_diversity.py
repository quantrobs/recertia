"""Write-time application-session counter for SkillStats (ADR-0015)."""

from __future__ import annotations

from contracts.stats import SkillStats
from recertia.memory.procedural.store import SkillStore


def note_apply_session(
    store: SkillStore,
    *,
    skill_id: str,
    version: int,
    session_id: str,
) -> SkillStats:
    """Increment distinct application sessions. O(sample). Does not rewrite SkillVersion."""

    stats = store.get_stats(skill_id, version)
    updated = stats.model_copy(update={"apply_diversity": stats.apply_diversity.note(session_id)})
    store.write_stats(updated)
    return updated
