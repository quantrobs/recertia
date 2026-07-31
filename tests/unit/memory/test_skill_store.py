from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from fandea.memory.procedural.hygiene import require_clean, scan_skill
from fandea.memory.procedural.seeds import add_gitignore_entry, seed_stats, seed_status_draft
from fandea.memory.procedural.store import ImmutabilityError, SkillStore

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _minimal_version(skill_id: str = "demo-skill", secret: str | None = None) -> SkillVersion:
    intent = "A minimal demo skill used only in unit tests for the store."
    if secret:
        intent = f"{intent} api_key={secret}"
    return SkillVersion(
        skill_id=skill_id,
        version=1,
        title="Demo skill for unit tests",
        intent=intent,
        task_class="repo-chore",
        steps=[Step(id="noop", tool="shell", intent="Do nothing useful here.", inputs={"command": "true"})],
        certification_criteria=[
            SkillCertificationCriterion(
                id="ok",
                kind="command",
                run="true",
                weight=1.0,
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="ok",
                    negative_fixture="false",
                    rejected=True,
                    checked_at=_NOW,
                ),
            )
        ],
        provenance=Provenance(
            distilled_from_run="unit",
            distilled_at=_NOW,
            curation="human_authored",
            derivation="hand_authored",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=_NOW),
    )


def test_write_version_is_immutable(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = add_gitignore_entry()
    store.write_version(v)
    with pytest.raises(ImmutabilityError):
        store.write_version(v)


def test_write_status_requires_version(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = add_gitignore_entry()
    with pytest.raises(FileNotFoundError):
        store.write_status(seed_status_draft(v))


def test_hygiene_rejects_secrets() -> None:
    dirty = _minimal_version(secret="supersecretvalue123456")
    hygiene = scan_skill(dirty)
    assert hygiene.secret_scan == "failed"
    with pytest.raises(ValueError):
        require_clean(dirty)


def test_round_trip_status_stats(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = add_gitignore_entry()
    store.write_version(v)
    store.write_status(seed_status_draft(v))
    store.write_stats(seed_stats(v))
    assert store.get_version(v.skill_id, v.version).title == v.title
    assert store.get_status(v.skill_id, v.version).lifecycle == "draft"
