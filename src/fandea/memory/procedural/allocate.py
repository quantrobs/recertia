"""Atomic skill version allocation (M9 concurrency).

Concurrent writers for the same ``skill_id`` take exclusive versions with no
gaps or duplicates. Allocation reserves a version number under a per-skill lock;
writes consume the reservation under the same lock family.
"""

from __future__ import annotations

import threading
from pathlib import Path

from contracts.skill import SkillVersion
from fandea.memory.procedural.store import SkillStore

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_reserved: dict[str, set[int]] = {}


def _lock_for(skill_id: str) -> threading.Lock:
    with _locks_guard:
        if skill_id not in _locks:
            _locks[skill_id] = threading.Lock()
        return _locks[skill_id]


def _existing_versions(skills_dir: Path, skill_id: str) -> list[int]:
    skill_dir = skills_dir / skill_id
    if not skill_dir.is_dir():
        return []
    return [
        int(p.name[1:])
        for p in skill_dir.iterdir()
        if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()
    ]


def allocate_next_version(store: SkillStore, skill_id: str) -> int:
    """Reserve the next free version number for ``skill_id`` (gap/dupe-free under concurrency)."""

    with _lock_for(skill_id):
        existing = _existing_versions(store.root, skill_id)
        reserved = _reserved.setdefault(skill_id, set())
        n = max([0, *existing, *reserved]) + 1
        reserved.add(n)
        return n


def write_version_exclusive(store: SkillStore, version: SkillVersion) -> Path:
    """Write a skill version under the per-skill exclusive lock."""

    with _lock_for(version.skill_id):
        path = store.write_version(version)
        reserved = _reserved.get(version.skill_id)
        if reserved is not None:
            reserved.discard(version.version)
        return path


def allocate_and_write(store: SkillStore, version: SkillVersion) -> SkillVersion:
    """Atomically allocate the next version and persist ``version``."""

    with _lock_for(version.skill_id):
        existing = _existing_versions(store.root, version.skill_id)
        reserved = _reserved.setdefault(version.skill_id, set())
        n = max([0, *existing, *reserved]) + 1
        reserved.add(n)
        stamped = version.model_copy(update={"version": n})
        path = store.write_version(stamped)
        reserved.discard(n)
        _ = path
        return stamped
