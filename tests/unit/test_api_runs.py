"""POST /v1/runs executes via GraphOrchestrator (CLI parity offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from fandea.api import create_app


def test_create_run_executes_graph_and_returns_terminal(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs"}, actor="test")
    client = TestClient(app)
    headers = {"X-API-Key": issued.secret}
    workdir = tmp_path / "work"
    workdir.mkdir()

    created = client.post(
        "/v1/runs",
        json={
            "request": "write output.txt",
            "task_class": "repo-chore",
            "run_id": "api-run-1",
            "workdir": str(workdir),
            "script": ["python3 -c \"open('output.txt','w').write('done')\""],
            "criteria": [
                {
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
            ],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["run_id"] == "api-run-1"
    assert body["terminal"] == "solved"
    assert body["status"] == "solved"
    assert body["route_log"]
    assert (workdir / "output.txt").read_text() == "done"

    got = client.get("/v1/runs/api-run-1", headers=headers)
    assert got.status_code == 200
    assert got.json()["terminal"] == "solved"


def test_create_run_without_script_still_reaches_terminal(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs"}, actor="test")
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
