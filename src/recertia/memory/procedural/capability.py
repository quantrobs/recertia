"""Narrow skill-store surface for T0 / task-plane nodes (candidate writes only)."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus
from recertia.memory.procedural.store import SkillStore


@dataclass(frozen=True)
class CandidateSkillStoreAdapter:
    """Expose only candidate writes + reads; hide status/stats mutation and promote paths."""

    _store: SkillStore

    def write_candidate(self, version: SkillVersion) -> SkillVersion:
        return self._store.write_candidate(version)

    def get_version(self, skill_id: str, version: int) -> SkillVersion:
        return self._store.get_version(skill_id, version)

    def get_status(self, skill_id: str, version: int) -> SkillStatus:
        return self._store.get_status(skill_id, version)

    def iter_loaded(self) -> list[tuple[SkillVersion, SkillStatus, SkillStats]]:
        return self._store.iter_loaded()

    def library_fingerprint(self) -> str:
        return self._store.library_fingerprint()
