"""Composite skill resolution and transitive invalidation (M8)."""

from __future__ import annotations

from contracts.skill import SkillVersion
from contracts.status import SkillStatus
from recertia.memory.procedural.store import SkillStore


class CompositionError(Exception):
    """Cycle, depth, or missing child."""


MAX_DEPTH = 3


def resolve_uses(
    store: SkillStore, version: SkillVersion, *, depth: int = 0
) -> list[SkillVersion]:
    if depth > MAX_DEPTH:
        raise CompositionError(f"uses depth exceeds {MAX_DEPTH}")
    resolved: list[SkillVersion] = []
    seen: set[tuple[str, int]] = set()

    def walk(ver: SkillVersion, path: list[tuple[str, int]], d: int) -> None:
        key = (ver.skill_id, ver.version)
        if key in path:
            raise CompositionError(f"cycle: {path + [key]}")
        if d > MAX_DEPTH:
            raise CompositionError(f"depth>{MAX_DEPTH}")
        for use in ver.uses:
            child = store.get_version(use.skill_id, use.version)
            status = store.get_status(use.skill_id, use.version)
            if status.lifecycle == "quarantined":
                raise CompositionError(
                    f"child {use.skill_id}@v{use.version} quarantined; parent blocked"
                )
            if status.lifecycle != "approved" or not status.active:
                raise CompositionError(
                    f"child {use.skill_id}@v{use.version} not approved+active"
                )
            ck = (child.skill_id, child.version)
            if ck not in seen:
                seen.add(ck)
                resolved.append(child)
            walk(child, path + [key], d + 1)

    walk(version, [], depth)
    return resolved


def mean_composition_depth(store: SkillStore) -> float:
    depths: list[int] = []
    for version, status, _stats in store.iter_loaded():
        if status.lifecycle != "approved":
            continue
        depths.append(_depth(store, version))
    return sum(depths) / len(depths) if depths else 0.0


def _depth(store: SkillStore, version: SkillVersion) -> int:
    if not version.uses:
        return 0
    return 1 + max(
        (_depth(store, store.get_version(u.skill_id, u.version)) for u in version.uses),
        default=0,
    )


def quarantine_child_blocks_parents(
    store: SkillStore, child_id: str, child_version: int
) -> list[SkillStatus]:
    """Quarantine child and mark pinning parents needs_recert (not approved-retrievable)."""

    child_status = store.get_status(child_id, child_version)
    store.write_status(
        child_status.model_copy(update={"lifecycle": "quarantined", "active": False})
    )
    touched: list[SkillStatus] = []
    for version, status, _stats in store.iter_loaded():
        if any(u.skill_id == child_id and u.version == child_version for u in version.uses):
            new_status = status.model_copy(
                update={"lifecycle": "needs_recert", "active": False}
            )
            store.write_status(new_status)
            touched.append(new_status)
    return touched
