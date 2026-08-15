"""Seed status/stats helpers and test-only approved seeder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts.stats import SkillStats
from contracts.status import Certification, SkillStatus

if TYPE_CHECKING:
    from contracts.skill import SkillVersion
    from recertia.memory.procedural.store import SkillStore


def seed_status_draft(version: SkillVersion) -> SkillStatus:
    return SkillStatus(
        skill_id=version.skill_id,
        version=version.version,
        lifecycle="draft",
        active=False,
        certification=Certification(
            tool_fingerprint={"python": "3.12", "pytest": "8.3.4"},
            recert_status="never",
        ),
    )


def seed_stats(version: SkillVersion) -> SkillStats:
    return SkillStats(skill_id=version.skill_id, version=version.version)


def seed_approved_for_tests(
    store: SkillStore,
    version: SkillVersion,
    *,
    active: bool = True,
    certification: Certification | None = None,
    write_version: bool = True,
) -> SkillStatus:
    """Test-only seeder: write ``lifecycle=approved`` via the unchecked store helper.

    Production code must use ``promote_to_approved``; this bypasses that gate for fixtures.
    """

    if write_version:
        dest = store.version_dir(version.skill_id, version.version) / "version.json"
        if not dest.exists():
            store.write_version(version)
    status = SkillStatus(
        skill_id=version.skill_id,
        version=version.version,
        lifecycle="approved",
        active=active,
        certification=certification
        or Certification(
            model_validated_on="test-seed",
            tool_fingerprint={"python": "3.12"},
            recert_status="fresh",
        ),
    )
    store._write_status_unchecked(status)
    store.write_stats(SkillStats(skill_id=version.skill_id, version=version.version))
    return status
