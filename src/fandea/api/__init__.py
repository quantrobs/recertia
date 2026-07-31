"""FastAPI surface: health, runs (GraphOrchestrator), metrics dashboard, blob digests.

``POST /v1/runs`` executes offline via ``GraphOrchestrator.start`` (same path as
``fandea run``), not an enqueue-only stub. Optional CLI-parity fields: ``criteria``,
``script``, ``budget``, ``workdir``, ``arm``.
"""

from __future__ import annotations

import json
import re
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
from fandea.api.auth import ApiKeyStore, Principal, require_scope, validate_tenant_id
from fandea.graph.engine import GraphOrchestrator
from fandea.store.blobs import FilesystemBlobStore, normalize_blob_digest
from fandea.telemetry import get_telemetry, render_dashboard

DEFAULT_ROOT = Path(".fandea")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(
            status_code=400,
            detail="run_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
        )
    return run_id


def _tenant_blob_root(root: Path, tenant_id: str) -> Path:
    """Resolve a tenant blob directory and refuse path escape."""

    validate_tenant_id(tenant_id)
    base = (root / "blobs").resolve()
    candidate = (base / tenant_id).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid tenant blob root") from exc
    return candidate


def _workspaces_root(root: Path) -> Path:
    return (root / "workspaces").resolve()


def _canonical_run_workdir(root: Path, tenant_id: str, run_id: str) -> Path:
    """Always resolve under ``root/workspaces/<tenant_id>/<run_id>``; reject escapes."""

    validate_tenant_id(tenant_id)
    run_id = _validate_run_id(run_id)
    base = _workspaces_root(root)
    candidate = (base / tenant_id / run_id).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="workdir escapes workspaces root") from exc
    return candidate


def _resolve_create_workdir(root: Path, tenant_id: str, run_id: str, workdir: str | None) -> Path:
    """Map optional caller ``workdir`` under the canonical run workspace only.

    Absolute paths and ``..`` escapes are rejected. Relative values are resolved under
    ``root/workspaces/<tenant_id>/<run_id>``.
    """

    base = _canonical_run_workdir(root, tenant_id, run_id)
    if workdir is None or workdir == "":
        return base
    ref = Path(workdir)
    if ref.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="workdir must be relative to the run workspace (absolute paths rejected)",
        )
    candidate = (base / ref).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="workdir escapes run workspace") from exc
    return candidate


def _workdir_meta_path(root: Path, tenant_id: str, run_id: str) -> Path:
    return root / "runs" / tenant_id / run_id / "workdir.json"


def _persist_workdir(root: Path, tenant_id: str, run_id: str, workdir: Path) -> None:
    meta = _workdir_meta_path(root, tenant_id, run_id)
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps({"workdir": str(workdir.resolve())}) + "\n",
        encoding="utf-8",
    )


def _load_persisted_workdir(root: Path, tenant_id: str, run_id: str) -> Path | None:
    meta = _workdir_meta_path(root, tenant_id, run_id)
    if not meta.exists():
        return None
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
        stored = Path(str(payload["workdir"])).resolve()
    except (json.JSONDecodeError, KeyError, OSError, TypeError):
        return None
    base = _canonical_run_workdir(root, tenant_id, run_id)
    try:
        stored.relative_to(base)
    except ValueError:
        return None
    return stored


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
    # Keyed by (tenant_id, run_id) so tenants cannot collide on run_id.
    runs: dict[tuple[str, str], RunRecord] = {}
    app = FastAPI(title="Fandea", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", response_model=RunRecord)
    def create_run(
        body: RunCreate, principal: Principal = Depends(require_scope("runs", key_store))
    ) -> RunRecord:
        run_id = _validate_run_id(body.run_id or f"run-{uuid4().hex[:12]}")
        run_key = (principal.tenant_id, run_id)
        if run_key in runs:
            raise HTTPException(status_code=409, detail="run_id already exists")

        workdir = _resolve_create_workdir(root, principal.tenant_id, run_id, body.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        _persist_workdir(root, principal.tenant_id, run_id, workdir)

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
        runs[run_key] = rec
        get_telemetry().emit(
            "run.finished",
            tenant_id=principal.tenant_id,
            run_id=run_id,
            terminal=state.terminal,
        )
        return rec

    @app.get("/v1/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str, principal: Principal = Depends(require_scope("runs", key_store))) -> RunRecord:
        run_id = _validate_run_id(run_id)
        run_key = (principal.tenant_id, run_id)
        if run_key in runs:
            return runs[run_key]
        loaded = _load_from_checkpoints(root, principal.tenant_id, run_id)
        if loaded is None:
            raise HTTPException(status_code=404, detail="run not found")
        runs[run_key] = loaded
        return loaded

    @app.post("/v1/runs/{run_id}/resume", response_model=RunRecord)
    def resume_run(
        run_id: str, principal: Principal = Depends(require_scope("runs", key_store))
    ) -> RunRecord:
        run_id = _validate_run_id(run_id)
        run_key = (principal.tenant_id, run_id)
        # Resume MUST reuse the persisted create workdir — never invent a new path.
        workdir = _load_persisted_workdir(root, principal.tenant_id, run_id)
        if workdir is None:
            workdir = _canonical_run_workdir(root, principal.tenant_id, run_id)
        if not workdir.exists():
            raise HTTPException(status_code=404, detail="run workdir not found")
        orch = GraphOrchestrator(root / "runs" / principal.tenant_id)
        try:
            state = orch.resume(run_id, workdir=workdir)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            orch.close()

        existing = runs.get(run_key)
        rec = _record_from_state(
            run_id=run_id,
            request=existing.request if existing else state.task.request,
            task_class=(existing.task_class if existing else (state.task.task_class or "repo-chore")),
            tenant_id=principal.tenant_id,
            state=state,
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
        )
        runs[run_key] = rec
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
        try:
            key = normalize_blob_digest(digest)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="blob not found") from exc
        blobs = blobs_by_tenant.setdefault(
            principal.tenant_id, FilesystemBlobStore(_tenant_blob_root(root, principal.tenant_id))
        )
        try:
            data = blobs.get(key)
        except (FileNotFoundError, ValueError) as exc:
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
