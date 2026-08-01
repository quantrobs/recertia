"""Skill linting: structural (Pydantic) + semantic profiles + uses-DAG checks (M1)."""

from __future__ import annotations

from contracts.profiles import validate_approved_skill, validate_candidate_skill
from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus
from recertia.memory.procedural.store import SkillStore


def lint_skill(
    version: SkillVersion,
    status: SkillStatus,
    stats: SkillStats | None = None,
    *,
    store: SkillStore | None = None,
) -> list[str]:
    """Return violation strings; empty means the skill is structurally + semantically clean."""

    violations: list[str] = []
    stats = stats or SkillStats(skill_id=version.skill_id, version=version.version)

    if status.lifecycle in ("candidate", "shadow", "approved"):
        violations.extend(validate_candidate_skill(version, status))
    if status.lifecycle == "approved":
        violations.extend(validate_approved_skill(version, status, stats))

    if store is not None:
        violations.extend(_check_uses_resolve(version, store))
        violations.extend(_check_uses_acyclic(version, store))

    return violations


def _check_uses_resolve(version: SkillVersion, store: SkillStore) -> list[str]:
    violations: list[str] = []
    for use in version.uses:
        try:
            store.get_version(use.skill_id, use.version)
        except FileNotFoundError:
            violations.append(
                f"uses entry {use.skill_id}@v{use.version} does not exist in the skill store"
            )
    return violations


def _check_uses_acyclic(version: SkillVersion, store: SkillStore, *, max_depth: int = 3) -> list[str]:
    """Walk the ``uses`` DAG; reject cycles and depth > 3 (specs §2.4, §14)."""

    violations: list[str] = []

    def walk(skill_id: str, ver: int, path: list[tuple[str, int]], depth: int) -> None:
        key = (skill_id, ver)
        if key in path:
            cycle = " -> ".join(f"{s}@v{v}" for s, v in path + [key])
            violations.append(f"uses graph contains a cycle: {cycle}")
            return
        if depth > max_depth:
            violations.append(
                f"uses depth exceeds {max_depth} at {skill_id}@v{ver} "
                f"(path: {' -> '.join(f'{s}@v{v}' for s, v in path)})"
            )
            return
        try:
            child = store.get_version(skill_id, ver)
        except FileNotFoundError:
            return
        for use in child.uses:
            walk(use.skill_id, use.version, path + [key], depth + 1)

    for use in version.uses:
        walk(use.skill_id, use.version, [(version.skill_id, version.version)], 1)
    return violations


def lint_store(store: SkillStore) -> dict[str, list[str]]:
    """Lint every version in the store; returns ``{skill_id@version: [violations]}`` (empty ok)."""

    report: dict[str, list[str]] = {}
    for version, status, stats in store.iter_loaded():
        key = f"{version.skill_id}@v{version.version}"
        report[key] = lint_skill(version, status, stats, store=store)
    return report
