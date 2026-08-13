from __future__ import annotations

from pathlib import Path

import pytest

from contracts.examples import (
    bump_python_dep_stats,
    bump_python_dep_status,
    bump_python_dep_version,
)
from recertia.memory.procedural.apply_diversity import skill_identity
from recertia.memory.procedural.store import SkillStore

pytest.importorskip("fastapi")


def test_console_identity_split(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from recertia.api import create_app

    skills = tmp_path / "skills"
    store = SkillStore(skills)
    version = bump_python_dep_version()
    store.write_version(version)
    store._write_status_unchecked(bump_python_dep_status())
    store.write_stats(bump_python_dep_stats())

    app = create_app(root=tmp_path / "api-root", skills_root=skills)
    issued = app.state.api_keys.issue(
        tenant_id="t1",
        scopes={"runs", "metrics", "exec", "admin"},
        actor="test",
    )
    client = TestClient(app)
    res = client.get(
        f"/v1/skills/{version.skill_id}/versions/{version.version}",
        headers={"X-API-Key": issued.secret},
    )
    assert res.status_code == 200
    body = res.json()
    identity = body["identity"]
    expected = skill_identity(version, store.get_stats(version.skill_id, version.version))
    assert identity["authoring"]["source_run_ids"] == expected["authoring"]["source_run_ids"]
    assert identity["authoring"]["source_run_ids"] == list(version.provenance.source_run_ids)
    assert (
        identity["applications"]["distinct_apply_sessions"]
        == store.get_stats(version.skill_id, version.version).apply_diversity.distinct_apply_sessions
    )
    assert identity["applications"]["floor"] == expected["applications"]["floor"]
    assert "version" in body and "stats" in body
    assert body["live_mix"]["reason"] == "live"
    assert body["live_mix"]["active"] is True
