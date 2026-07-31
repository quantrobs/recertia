from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from contracts.status import SkillStatus
from fandea.memory.procedural.hygiene import require_clean, scan_skill
from fandea.memory.procedural.seeds import (
    add_gitignore_entry,
    seed_approved_for_tests,
    seed_stats,
    seed_status_draft,
)
from fandea.memory.procedural.store import ApprovedLifecycleError, ImmutabilityError, SkillStore

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


def test_write_candidate_writes_version_status_stats(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = _minimal_version("cand-skill")
    store.write_candidate(v)
    assert store.get_status("cand-skill", 1).lifecycle == "candidate"
    assert store.get_status("cand-skill", 1).active is False
    assert store.get_stats("cand-skill", 1).skill_id == "cand-skill"


def test_write_status_rejects_approved_transition(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = _minimal_version("gate-skill")
    store.write_candidate(v)
    with pytest.raises(ApprovedLifecycleError, match="promote_to_approved"):
        store.write_status(
            SkillStatus(skill_id="gate-skill", version=1, lifecycle="approved", active=True)
        )
    assert store.get_status("gate-skill", 1).lifecycle == "candidate"


def test_seed_approved_for_tests_bypasses_gate(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = _minimal_version("seed-approved")
    status = seed_approved_for_tests(store, v, active=True)
    assert status.lifecycle == "approved"
    assert store.get_status("seed-approved", 1).active is True
    # Already-approved updates (e.g. active toggle) remain allowed.
    store.write_status(
        SkillStatus(skill_id="seed-approved", version=1, lifecycle="approved", active=False)
    )
    assert store.get_status("seed-approved", 1).active is False


def test_write_candidate_skips_existing_version(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    v = _minimal_version("prewritten")
    store.write_version(v)
    store.write_candidate(v)
    assert store.get_status("prewritten", 1).lifecycle == "candidate"
