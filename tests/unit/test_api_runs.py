"""POST /v1/runs executes via GraphOrchestrator (CLI parity offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from recertia.api import create_app
from tests.support.http import error_text


def _proven_output_criterion() -> dict:
    return {
        "id": "output-exists",
        "kind": "command",
        "run": "test -f output.txt",
        "source": "caller",
        "weight": 1.0,
        "sensitivity_proof": {
            "criterion_id": "output-exists",
            "negative_fixture": "empty workspace",
            "rejected": True,
            "checked_at": "2026-01-01T00:00:00Z",
        },
    }


def test_create_run_executes_graph_and_returns_terminal(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs", "exec"}, actor="test")
    client = TestClient(app)
    headers = {"X-API-Key": issued.secret}

    created = client.post(
        "/v1/runs",
        json={
            "request": "write output.txt",
            "task_class": "repo-chore",
            "run_id": "api-run-1",
            "script": ["python3 -c \"open('output.txt','w').write('done')\""],
            "criteria": [_proven_output_criterion()],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["run_id"] == "api-run-1"
    assert body["terminal"] == "solved"
    assert body["status"] == "solved"
    assert body["route_log"]
    workdir = tmp_path / "api-root" / "workspaces" / "t1" / "api-run-1"
    assert (workdir / "output.txt").read_text() == "done"

    got = client.get("/v1/runs/api-run-1", headers=headers)
    assert got.status_code == 200
    assert got.json()["terminal"] == "solved"


def test_create_run_without_script_still_reaches_terminal(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs", "exec"}, actor="test")
    client = TestClient(app)
    headers = {"X-API-Key": issued.secret}

    created = client.post(
        "/v1/runs",
        json={
            "request": "do chore",
            "task_class": "repo-chore",
            "budget": {"max_attempts": 1},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["terminal"] in {"solved", "unsolved", "abstained"}
    assert body["status"] == body["terminal"]


def test_create_run_rejects_absolute_and_escaped_workdir(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs", "exec"}, actor="test")
    client = TestClient(app)
    headers = {"X-API-Key": issued.secret}

    absolute = client.post(
        "/v1/runs",
        json={
            "request": "x",
            "run_id": "abs-wd",
            "workdir": str(tmp_path / "outside"),
            "budget": {"max_attempts": 1},
        },
        headers=headers,
    )
    assert absolute.status_code == 400
    assert "absolute" in error_text(absolute).lower()

    escaped = client.post(
        "/v1/runs",
        json={
            "request": "x",
            "run_id": "esc-wd",
            "workdir": "../other-tenant",
            "budget": {"max_attempts": 1},
        },
        headers=headers,
    )
    assert escaped.status_code == 400
    assert "escape" in error_text(escaped).lower()


def test_relative_workdir_persists_for_resume(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs", "exec"}, actor="test")
    client = TestClient(app)
    headers = {"X-API-Key": issued.secret}

    created = client.post(
        "/v1/runs",
        json={
            "request": "write output.txt",
            "run_id": "persist-wd",
            "workdir": "nested/job",
            "script": ["python3 -c \"open('output.txt','w').write('nested')\""],
            "criteria": [_proven_output_criterion()],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    expected = tmp_path / "api-root" / "workspaces" / "t1" / "persist-wd" / "nested" / "job"
    assert (expected / "output.txt").read_text() == "nested"

    meta = tmp_path / "api-root" / "runs" / "t1" / "persist-wd" / "workdir.json"
    assert meta.exists()
    import json

    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert Path(payload["workdir"]).resolve() == expected.resolve()
    assert payload.get("kind", "sandbox") == "sandbox"

    # Clear in-memory cache to force resume to load persisted workdir.
    app.state.runs.clear()
    resumed = client.post("/v1/runs/persist-wd/resume", headers=headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["terminal"] == "solved"


def test_cross_tenant_run_id_isolation(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    a = app.state.api_keys.issue(tenant_id="tenant-a", scopes={"runs", "exec"}, actor="a")
    b = app.state.api_keys.issue(tenant_id="tenant-b", scopes={"runs", "exec"}, actor="b")
    client = TestClient(app)

    created = client.post(
        "/v1/runs",
        json={
            "request": "tenant a chore",
            "run_id": "shared-id",
            "budget": {"max_attempts": 1},
            "script": ["true"],
        },
        headers={"X-API-Key": a.secret},
    )
    assert created.status_code == 200, created.text

    # Same run_id under another tenant is allowed (keys are tenant-scoped).
    other = client.post(
        "/v1/runs",
        json={
            "request": "tenant b chore",
            "run_id": "shared-id",
            "budget": {"max_attempts": 1},
            "script": ["true"],
        },
        headers={"X-API-Key": b.secret},
    )
    assert other.status_code == 200, other.text

    # Tenant B must not read tenant A's in-memory/checkpoint record by run_id alone.
    # After creating its own run, get returns B's record, not A's request text.
    got_b = client.get("/v1/runs/shared-id", headers={"X-API-Key": b.secret})
    assert got_b.status_code == 200
    assert got_b.json()["request"] == "tenant b chore"
    assert got_b.json()["tenant_id"] == "tenant-b"

    got_a = client.get("/v1/runs/shared-id", headers={"X-API-Key": a.secret})
    assert got_a.status_code == 200
    assert got_a.json()["request"] == "tenant a chore"
    assert got_a.json()["tenant_id"] == "tenant-a"
