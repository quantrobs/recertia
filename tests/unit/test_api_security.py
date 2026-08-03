"""API security: local fail-closed, exec scope for scripts, blob caps, key format."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from recertia.api import create_app
from recertia.api.auth import ApiKeyStore
from recertia.solver.container import ensure_api_execution_ready
from recertia.solver.sandbox import SandboxError
from tests.support.platform import skip_posix_mode_bits


def test_api_refuses_local_backend_without_break_glass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECERTIA_EXECUTION_BACKEND", "local")
    monkeypatch.delenv("RECERTIA_API_ALLOW_LOCAL_EXEC", raising=False)
    with pytest.raises(SandboxError, match="not allowed for the HTTP API"):
        ensure_api_execution_ready()


def test_structured_api_key_authenticates_in_one_lookup(tmp_path: Path) -> None:
    keys = ApiKeyStore(tmp_path / "keys.sqlite")
    issued = keys.issue(tenant_id="t1", scopes={"runs"}, actor="op")
    assert issued.secret.startswith("rec_key_")
    assert issued.key_id in issued.secret
    principal = keys.authenticate(issued.secret)
    assert principal is not None
    assert principal.key_id == issued.key_id


def test_script_requires_exec_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECERTIA_EXECUTION_BACKEND", "local")
    monkeypatch.setenv("RECERTIA_API_ALLOW_LOCAL_EXEC", "1")
    app = create_app(root=tmp_path / "api-root")
    runs_only = app.state.api_keys.issue(tenant_id="t1", scopes={"runs"}, actor="test")
    client = TestClient(app)
    denied = client.post(
        "/v1/runs",
        json={
            "request": "x",
            "run_id": "needs-exec",
            "script": ["true"],
            "budget": {"max_attempts": 1},
        },
        headers={"X-API-Key": runs_only.secret},
    )
    assert denied.status_code == 403
    assert "exec" in denied.json()["detail"]


def test_blob_upload_rejects_oversized_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECERTIA_MAX_BLOB_BYTES", "32")
    # Re-import clamp is read at module load — patch the module attribute.
    import recertia.api as api_mod

    monkeypatch.setattr(api_mod, "_MAX_BLOB_BYTES", 32)
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"blobs"}, actor="test")
    client = TestClient(app)
    resp = client.post(
        "/v1/blobs",
        json={"data": "x" * 64},
        headers={"X-API-Key": issued.secret},
    )
    assert resp.status_code == 413


@skip_posix_mode_bits
def test_workdir_not_world_writable_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recertia.solver.container import ensure_workdir_writable_by_container

    monkeypatch.delenv("RECERTIA_WORKDIR_WORLD_WRITE", raising=False)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    ensure_workdir_writable_by_container(workdir)
    mode = workdir.stat().st_mode & 0o777
    assert mode & 0o002 == 0  # other-write must be off
