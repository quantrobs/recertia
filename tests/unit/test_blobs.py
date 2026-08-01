"""Blob digest confinement: sha256 + 64 hex only; no path traversal."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from recertia.api import create_app
from recertia.store.blobs import FilesystemBlobStore, normalize_blob_digest


def test_normalize_blob_digest_requires_sha256_and_64_hex() -> None:
    digest = "sha256:" + ("a" * 64)
    assert normalize_blob_digest(digest) == digest
    assert normalize_blob_digest("a" * 64) == digest
    with pytest.raises(ValueError):
        normalize_blob_digest("sha256:../etc/passwd")
    with pytest.raises(ValueError):
        normalize_blob_digest("/tmp/abs")
    with pytest.raises(ValueError):
        normalize_blob_digest("sha256:" + ("g" * 64))
    with pytest.raises(ValueError):
        normalize_blob_digest("sha256:" + ("a" * 63))


def test_filesystem_blob_store_rejects_traversal(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    digest = store.put(b"payload")
    assert store.get(digest) == b"payload"

    with pytest.raises(ValueError):
        store.get("sha256:../../etc/passwd" + ("0" * 48))
    with pytest.raises(ValueError):
        store.get("../" + ("b" * 61))
    with pytest.raises(ValueError):
        store.get("/absolute/" + ("c" * 54))
    assert store.exists("sha256:../escape" + ("d" * 55)) is False


def test_api_get_blob_404_on_traversal_and_absolute(tmp_path: Path) -> None:
    app = create_app(root=tmp_path / "api-root")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"blobs"}, actor="test")
    client = TestClient(app)
    headers = {"X-API-Key": issued.secret}

    put = client.post("/v1/blobs", json={"data": "hello"}, headers=headers)
    assert put.status_code == 200
    digest = put.json()["digest"]
    assert client.get(f"/v1/blobs/{digest}", headers=headers).status_code == 200
    # Bare 64-hex form remains accepted and normalized.
    assert client.get(f"/v1/blobs/{digest.removeprefix('sha256:')}", headers=headers).status_code == 200

    assert client.get("/v1/blobs/sha256:../../etc/passwd", headers=headers).status_code == 404
    assert client.get("/v1/blobs/../etc/passwd", headers=headers).status_code == 404
    # Absolute-looking path segment
    assert client.get("/v1/blobs/%2Ftmp%2Fsecret", headers=headers).status_code == 404
