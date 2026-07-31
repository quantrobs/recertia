"""Atomic skill version allocation (M9 concurrency).

Concurrent writers for the same ``skill_id`` take exclusive versions with no
gaps or duplicates. Allocation reserves a version number under a per-skill lock;
writes consume the reservation under the same lock family.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from contracts.skill import SkillVersion
from fandea.memory.procedural.store import SkillStore


def _existing_versions(skills_dir: Path, skill_id: str) -> list[int]:
    skill_dir = skills_dir / skill_id
    if not skill_dir.is_dir():
        return []
    return [
        int(p.name[1:])
        for p in skill_dir.iterdir()
        if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()
    ]


def _allocation_db(store: SkillStore) -> Path:
    return store.root / ".version-allocations.sqlite3"


def _init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reservations (
            skill_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            PRIMARY KEY (skill_id, version)
        )
        """
    )
    return conn


@contextmanager
def _skill_lock(store: SkillStore, skill_id: str):
    lock_dir = store.root / ".version-locks"
    lock_dir.mkdir(exist_ok=True)
    digest = hashlib.sha256(skill_id.encode()).hexdigest()
    fd = os.open(lock_dir / f"{digest}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def allocate_next_version(store: SkillStore, skill_id: str) -> int:
    """Durably reserve the next free version across processes."""

    with _skill_lock(store, skill_id):
        conn = _init_db(_allocation_db(store))
        try:
            conn.execute("BEGIN IMMEDIATE")
            reserved = [
                int(row[0])
                for row in conn.execute(
                    "SELECT version FROM reservations WHERE skill_id = ?", (skill_id,)
                )
            ]
            existing = _existing_versions(store.root, skill_id)
            n = max([0, *existing, *reserved]) + 1
            conn.execute(
                "INSERT INTO reservations (skill_id, version) VALUES (?, ?)", (skill_id, n)
            )
            conn.execute("COMMIT")
            return n
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def write_version_exclusive(store: SkillStore, version: SkillVersion) -> Path:
    """Write a reserved skill version under an inter-process exclusive lock."""

    with _skill_lock(store, version.skill_id):
        path = store.write_version(version)
        conn = _init_db(_allocation_db(store))
        try:
            conn.execute(
                "DELETE FROM reservations WHERE skill_id = ? AND version = ?",
                (version.skill_id, version.version),
            )
        finally:
            conn.close()
        return path


def allocate_and_write(store: SkillStore, version: SkillVersion) -> SkillVersion:
    """Atomically allocate the next version and persist ``version``."""

    with _skill_lock(store, version.skill_id):
        # Direct write while holding the same lock cannot race another process.  Do not create
        # a durable reservation here: a failed write must not leave an artificial version gap.
        n = max([0, *_existing_versions(store.root, version.skill_id)]) + 1
        stamped = version.model_copy(update={"version": n})
        path = store.write_version(stamped)
        _ = path
        return stamped
