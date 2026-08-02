"""Pilot Compose: criteria suggest drafts (never auto-lock)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from contracts.goal import Goal, compile_goal
from recertia.api import create_app
from recertia.console_compose import heuristic_suggest, stress_check, suggest_criteria


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    app = create_app(root=tmp_path / "api-root", skills_root=tmp_path / "skills")
    issued = app.state.api_keys.issue(
        tenant_id="t1",
        scopes={"runs", "metrics", "admin"},
        actor="test",
    )
    return TestClient(app), {"X-API-Key": issued.secret}


def test_heuristic_gitignore_draft() -> None:
    result = heuristic_suggest(context="Add *.pyc to .gitignore if missing")
    ids = {d.id for d in result.desired}
    assert "gitignore-exists" in ids
    assert "pyc-ignored" in ids
    assert result.source == "heuristic"
    assert "auto-locked" not in result.disclaimer.lower() or "never" in result.disclaimer.lower()


def test_large_brief_prefers_pack() -> None:
    result = heuristic_suggest(
        context=(
            "Re-architect the service into hexagonal layers (domain, application, adapters), "
            "replace ad-hoc persistence with a repository interface, add integration tests, "
            "and keep HTTP routes backward-compatible."
        )
    )
    assert result.pack
    assert any(w.code == "prefer_goal_pack" for w in result.warnings)


def test_stress_flags_vacuous_command() -> None:
    from recertia.console_compose import DraftDesired

    warnings = stress_check(
        [DraftDesired(id="x", kind="command", run="true")],
        [],
    )
    assert any(w.code == "vacuous_command" and w.severity == "block" for w in warnings)


def test_suggest_fallback_without_model() -> None:
    result = suggest_criteria(
        context="Add pytest.ini with testpaths=tests",
        use_model=False,
    )
    assert result.source == "heuristic"
    assert any(d.id == "pytest-ini" for d in result.desired)


def test_api_suggest_does_not_lock(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    resp = client.post(
        "/v1/goals/suggest",
        headers=headers,
        json={
            "context": "Add EditorConfig with Python indent settings",
            "task_class": "repo-chore",
            "use_model": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "heuristic"
    assert body["desired"]
    assert "disclaimer" in body
    assert body["blocked"] is False
    # Drafts must be applyable into a valid Goal + compile_goal
    desired = [
        {
            "id": d["id"],
            "kind": d["kind"],
            "weight": 1.0,
            **({k: d[k] for k in ("path", "pattern", "run") if d.get(k) is not None}),
        }
        for d in body["desired"]
    ]
    goal = Goal.model_validate(
        {
            "goal_id": "compose-test",
            "desired": desired,
            "constraints": [],
            "context": body["context"],
            "task_class": "repo-chore",
        }
    )
    criteria = compile_goal(goal)
    assert criteria


def test_api_suggest_requires_auth(tmp_path: Path) -> None:
    client, _headers = _client(tmp_path)
    resp = client.post(
        "/v1/goals/suggest",
        json={"context": "x", "use_model": False},
    )
    assert resp.status_code == 401


def test_empty_context_blocked() -> None:
    result = suggest_criteria(context="  ", use_model=False)
    assert any(w.code == "empty_context" for w in result.warnings)
