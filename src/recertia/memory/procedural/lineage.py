"""Authoring-source inverted index + async revoke queue (ADR-0015)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from contracts.skill import SkillVersion
from contracts.status import SkillStatus
from recertia.memory.procedural.store import SkillStore


class LineageIndex:
    """``source_id → [(skill_id, version)]``. Append-only; lookups are point gets."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, version: SkillVersion) -> None:
        keys = (
            [f"case:{i}" for i in version.provenance.source_case_ids]
            + [f"run:{i}" for i in version.provenance.source_run_ids]
            + [f"session:{i}" for i in version.provenance.source_session_ids]
            + [f"contributor:{i}" for i in version.provenance.source_contributor_ids]
        )
        if not keys:
            return
        target = f"{version.skill_id}@{version.version}"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                for key in keys:
                    fh.write(json.dumps({"source": key, "target": target}) + "\n")

    def lookup(self, source_kind: str, source_id: str) -> list[tuple[str, int]]:
        needle = f"{source_kind}:{source_id}"
        found: list[tuple[str, int]] = []
        if not self.path.exists():
            return found
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("source") != needle:
                    continue
                skill_id, _, ver = str(row["target"]).partition("@")
                found.append((skill_id, int(ver)))
        return found


class RevokeQueue:
    """Task-plane enqueues; Recertifier drains. ``record_dead_end`` stays O(1)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def enqueue(self, *, source_kind: str, source_id: str, reason: str) -> None:
        item = {
            "source_kind": source_kind,
            "source_id": source_id,
            "reason": reason,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item) + "\n")

    def drain(self, limit: int) -> list[dict]:
        if not self.path.exists() or limit <= 0:
            return []
        with self._lock:
            lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            taken = lines[:limit]
            rest = lines[limit:]
            self.path.write_text(("\n".join(rest) + "\n") if rest else "", encoding="utf-8")
        return [json.loads(ln) for ln in taken]


def _mark_needs_recert(store: SkillStore, skill_id: str, version: int) -> SkillStatus | None:
    try:
        status = store.get_status(skill_id, version)
    except FileNotFoundError:
        return None
    if status.lifecycle in ("quarantined", "deprecated", "needs_recert"):
        return None
    new_status = status.model_copy(update={"lifecycle": "needs_recert", "active": False})
    store.write_status(new_status)
    return new_status


def drain_revokes(
    store: SkillStore,
    index: LineageIndex,
    queue: RevokeQueue,
    *,
    max_writes: int = 50,
) -> list[SkillStatus]:
    """Mark intersecting versions and pinning parents ``needs_recert``. Caps writes per tick."""

    touched: list[SkillStatus] = []
    remaining = max_writes
    items = queue.drain(limit=max_writes)
    leftover: list[dict] = []
    parents_of: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for parent_ver, _status, _stats in store.iter_loaded():
        for use in parent_ver.uses:
            parents_of.setdefault((use.skill_id, use.version), []).append(
                (parent_ver.skill_id, parent_ver.version)
            )
    for item in items:
        if remaining <= 0:
            leftover.append(item)
            continue
        targets = index.lookup(item["source_kind"], item["source_id"])
        for skill_id, version in targets:
            if remaining <= 0:
                leftover.append(item)
                break
            marked = _mark_needs_recert(store, skill_id, version)
            if marked is not None:
                touched.append(marked)
                remaining -= 1
            for parent_id, parent_ver in parents_of.get((skill_id, version), []):
                if remaining <= 0:
                    break
                parent_marked = _mark_needs_recert(store, parent_id, parent_ver)
                if parent_marked is not None:
                    touched.append(parent_marked)
                    remaining -= 1
    for item in leftover:
        queue.enqueue(
            source_kind=item["source_kind"],
            source_id=item["source_id"],
            reason=item.get("reason") or "requeued",
        )
    return touched
