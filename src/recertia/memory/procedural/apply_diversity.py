"""Write-time application-session counter for SkillStats (ADR-0015)."""

from __future__ import annotations

from typing import Any

from contracts.skill import SkillVersion
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


def skill_identity(version: SkillVersion, stats: SkillStats) -> dict[str, Any]:
    """Console/API view: authoring on the version, applications on stats."""

    prov = version.provenance
    diversity = stats.apply_diversity
    return {
        "authoring": {
            "curation": prov.curation,
            "derivation": prov.derivation,
            "source_run_ids": list(prov.source_run_ids),
            "source_case_ids": list(prov.source_case_ids),
            "source_session_ids": list(prov.source_session_ids),
            "source_contributor_ids": list(prov.source_contributor_ids),
        },
        "applications": {
            "distinct_apply_sessions": diversity.distinct_apply_sessions,
            "apply_session_sample": list(diversity.apply_session_sample),
            "floor": diversity.floor,
        },
    }
