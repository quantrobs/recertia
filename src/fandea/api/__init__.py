"""FastAPI surface: health, runs, metrics dashboard, blob digests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from fandea.api.auth import Principal, require_scope
from fandea.store.blobs import FilesystemBlobStore
from fandea.telemetry import get_telemetry, render_dashboard, reset_telemetry

DEFAULT_ROOT = Path(".fandea")


class RunCreate(BaseModel):
    request: str = Field(min_length=1)
    task_class: str = "repo-chore"


class RunRecord(BaseModel):
    run_id: str
    request: str
    task_class: str
    status: str
    created_at: datetime


def create_app(*, root: Path | None = None) -> FastAPI:
    root = root or DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    blobs = FilesystemBlobStore(root / "blobs")
    runs: dict[str, RunRecord] = {}
    app = FastAPI(title="Fandea", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", response_model=RunRecord)
    def create_run(
        body: RunCreate, principal: Principal = Depends(require_scope("runs"))
    ) -> RunRecord:
        run_id = f"run-{uuid4().hex[:12]}"
        rec = RunRecord(
            run_id=run_id,
            request=body.request,
            task_class=body.task_class,
            status="accepted",
            created_at=datetime.now(timezone.utc),
        )
        runs[run_id] = rec
        get_telemetry().emit(
            "run.started", run_id=run_id, task_class=body.task_class, tenant=principal.tenant_id
        )
        return rec

    @app.get("/v1/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str, _principal: Principal = Depends(require_scope("runs"))) -> RunRecord:
        if run_id not in runs:
            raise HTTPException(status_code=404, detail="run not found")
        return runs[run_id]

    @app.post("/v1/blobs")
    def put_blob(
        payload: dict[str, Any], _principal: Principal = Depends(require_scope("blobs"))
    ) -> dict[str, str]:
        data = str(payload.get("data", "")).encode()
        digest = blobs.put(data, content_type=str(payload.get("content_type", "text/plain")))
        return {"digest": digest}

    @app.get("/v1/blobs/{digest}")
    def get_blob(
        digest: str, _principal: Principal = Depends(require_scope("blobs"))
    ) -> dict[str, Any]:
        key = digest if digest.startswith("sha256:") else f"sha256:{digest}"
        try:
            data = blobs.get(key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="blob not found") from exc
        return {"digest": key, "size": len(data), "text": data.decode(errors="replace")[:8000]}

    @app.get("/v1/metrics/dashboard")
    def dashboard(_principal: Principal = Depends(require_scope("metrics"))) -> dict[str, Any]:
        return render_dashboard(get_telemetry())

    @app.post("/v1/telemetry/reset")
    def telemetry_reset(_principal: Principal = Depends(require_scope("admin"))) -> dict[str, str]:
        reset_telemetry()
        return {"status": "reset"}

    app.state.root = root
    app.state.blobs = blobs
    app.state.runs = runs
    return app
