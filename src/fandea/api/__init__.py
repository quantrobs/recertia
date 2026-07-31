"""FastAPI surface: health, runs (GraphOrchestrator), metrics dashboard, blob digests.

``POST /v1/runs`` executes offline via ``GraphOrchestrator.start`` (same path as
``fandea run``), not an enqueue-only stub. Optional CLI-parity fields: ``criteria``,
``script``, ``budget``, ``workdir``, ``arm``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from contracts.budget import Budget
from contracts.common import Arm
from contracts.criteria import TaskCriterion
from contracts.run import Task
from fandea.api.auth import ApiKeyStore, Principal, require_scope
from fandea.graph.engine import GraphOrchestrator
from fandea.store.blobs import FilesystemBlobStore
from fandea.telemetry import get_telemetry, render_dashboard

DEFAULT_ROOT = Path(".fandea")


def _tenant_blob_root(root: Path, tenant_id: str) -> Path:
    """Resolve a tenant blob directory and refuse path escape."""

    base = (root / "blobs").resolve()
    candidate = (base / tenant_id).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid tenant blob root") from exc
    return candidate


class RunCreate(BaseModel):
    request: str = Field(min_length=1)
    task_class: str = "repo-chore"
    criteria: list[dict[str, Any]] | None = None
    script: list[str] | None = None
    budget: dict[str, Any] | None = None
    workdir: str | None = None
    run_id: str | None = None
    arm: Arm = "treatment"


class RunRecord(BaseModel):
    run_id: str
    request: str
    task_class: str
    status: str
    created_at: datetime
    tenant_id: str
    terminal: str | None = None
    failure_class: str | None = None
    attempt_no: int | None = None
    arm: str | None = None
    route_log: list[dict[str, Any]] | None = None


def create_app(*, root: Path | None = None) -> FastAPI:
    root = root or DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    key_store = ApiKeyStore(root / "api_keys.sqlite")
    blobs_by_tenant: dict[str, FilesystemBlobStore] = {}
    runs: dict[str, RunRecord] = {}
    app = FastAPI(title="Fandea", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", response_model=RunRecord)
    def create_run(
        body: RunCreate, principal: Principal = Depends(require_scope("runs", key_store))
    ) -> RunRecord:
        run_id = body.run_id or f"run-{uuid4().hex[:12]}"
        if run_id in runs:
            raise HTTPException(status_code=409, detail="run_id already exists")

        workdir = (
            Path(body.workdir)
            if body.workdir
            else root / "workspaces" / principal.tenant_id / run_id
        )
        workdir.mkdir(parents=True, exist_ok=True)

        task = Task(
            task_id=run_id,
            request=body.request,
            task_class=body.task_class,
            submitted_at=datetime.now(timezone.utc),
            submitted_by=principal.key_id,
        )
        criteria = [TaskCriterion.model_validate(c) for c in (body.criteria or [])]
        budget = Budget.model_validate(body.budget) if body.budget else Budget()

        get_telemetry().emit(
            "run.started",
            tenant_id=principal.tenant_id,
            run_id=run_id,
            task_class=body.task_class,
        )

        orch = GraphOrchestrator(root / "runs" / principal.tenant_id)
        try:
            state = orch.start(
                run_id,
                task,
                criteria,
                budget=budget,
                workdir=workdir,
                script=body.script,
                arm=body.arm,
            )
        except Exception as exc:
            get_telemetry().emit(
                "run.finished",
                tenant_id=principal.tenant_id,
                run_id=run_id,
                terminal="error",
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            orch.close()

        rec = _record_from_state(
            run_id=run_id,
            request=body.request,
            task_class=body.task_class,
            tenant_id=principal.tenant_id,
            state=state,
            created_at=datetime.now(timezone.utc),
        )
        runs[run_id] = rec
        get_telemetry().emit(
            "run.finished",
            tenant_id=principal.tenant_id,
            run_id=run_id,
            terminal=state.terminal,
        )
        return rec

    @app.get("/v1/runs/{run_id}", response_model=RunRecord)
    def get_run(
        run_id: str, principal: Principal = Depends(require_scope("runs", key_store))
    ) -> RunRecord:
        if run_id in runs and runs[run_id].tenant_id == principal.tenant_id:
            return runs[run_id]
        loaded = _load_from_checkpoints(root, principal.tenant_id, run_id)
        if loaded is None:
            raise HTTPException(status_code=404, detail="run not found")
        runs[run_id] = loaded
        return loaded

    @app.post("/v1/runs/{run_id}/resume", response_model=RunRecord)
    def resume_run(
        run_id: str, principal: Principal = Depends(require_scope("runs", key_store))
    ) -> RunRecord:
        workdir = root / "workspaces" / principal.tenant_id / run_id
        workdir.mkdir(parents=True, exist_ok=True)
        orch = GraphOrchestrator(root / "runs" / principal.tenant_id)
        try:
            state = orch.resume(run_id, workdir=workdir)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            orch.close()

        existing = runs.get(run_id)
        rec = _record_from_state(
            run_id=run_id,
            request=existing.request if existing else state.task.request,
            task_class=(
                existing.task_class
                if existing
                else (state.task.task_class or "repo-chore")
            ),
            tenant_id=principal.tenant_id,
            state=state,
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
        )
        runs[run_id] = rec
        return rec

    @app.post("/v1/blobs")
    def put_blob(
        payload: dict[str, Any],
        principal: Principal = Depends(require_scope("blobs", key_store)),
    ) -> dict[str, str]:
        blobs = blobs_by_tenant.setdefault(
            principal.tenant_id, FilesystemBlobStore(_tenant_blob_root(root, principal.tenant_id))
        )
        data = str(payload.get("data", "")).encode()
        digest = blobs.put(data, content_type=str(payload.get("content_type", "text/plain")))
        return {"digest": digest}

    @app.get("/v1/blobs/{digest}")
    def get_blob(
        digest: str, principal: Principal = Depends(require_scope("blobs", key_store))
    ) -> dict[str, Any]:
        blobs = blobs_by_tenant.setdefault(
            principal.tenant_id, FilesystemBlobStore(_tenant_blob_root(root, principal.tenant_id))
        )
        key = digest if digest.startswith("sha256:") else f"sha256:{digest}"
        try:
            data = blobs.get(key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="blob not found") from exc
        return {"digest": key, "size": len(data), "text": data.decode(errors="replace")[:8000]}

    @app.get("/v1/metrics/dashboard")
    def dashboard(
        principal: Principal = Depends(require_scope("metrics", key_store)),
    ) -> dict[str, Any]:
        return render_dashboard(get_telemetry(), tenant_id=principal.tenant_id)

    app.state.root = root
    app.state.api_keys = key_store
    app.state.blobs_by_tenant = blobs_by_tenant
    app.state.runs = runs
    return app


def _record_from_state(
    *,
    run_id: str,
    request: str,
    task_class: str,
    tenant_id: str,
    state: Any,
    created_at: datetime,
) -> RunRecord:
    terminal = state.terminal
    status = terminal if terminal else "running"
    failure_class = state.failure.failure_class if state.failure is not None else None
    route_log = [
        {
            "attempt_no": e.attempt_no,
            "node": e.node,
            "route": e.route,
            "reason": e.reason,
        }
        for e in state.route_log
    ]
    return RunRecord(
        run_id=run_id,
        request=request,
        task_class=task_class,
        status=status,
        created_at=created_at,
        tenant_id=tenant_id,
        terminal=terminal,
        failure_class=failure_class,
        attempt_no=state.attempt_no,
        arm=state.arm,
        route_log=route_log,
    )


def _load_from_checkpoints(root: Path, tenant_id: str, run_id: str) -> RunRecord | None:
    orch = GraphOrchestrator(root / "runs" / tenant_id)
    try:
        latest = orch.checkpoints.latest(run_id)
        if latest is None:
            return None
        _, _, _, state = latest
        return _record_from_state(
            run_id=run_id,
            request=state.task.request,
            task_class=state.task.task_class or "repo-chore",
            tenant_id=tenant_id,
            state=state,
            created_at=datetime.now(timezone.utc),
        )
    finally:
        orch.close()
