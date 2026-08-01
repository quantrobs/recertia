"""Product console HTTP routes (C0–C5). Registered onto the main FastAPI app."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from contracts.goal import Goal, compile_goal
from recertia.api.console_auth import (
    ConsoleUser,
    SessionStore,
    auth_mode,
    oidc_authorize_url,
    oidc_configured,
    oidc_exchange_code,
)
from recertia.api.events import RunEventLog
from recertia.api.jobs_store import JobRunStore
from recertia.api.quotas import QuotaStore
from recertia.console_templates import get_template_goal, list_templates
from recertia.evals.canary import run_judge_canary
from recertia.evals.metrics import build_metric_report
from recertia.evals.store import EvalStore
from recertia.graph.engine import GraphOrchestrator
from recertia.jobs import JobBudget, JobRunner
from recertia.jobs.workers import (
    correction_miner_from_reviewer_edits,
    curator_active_set_and_dedup,
    load_one_off_reasons,
    load_reviewer_edits,
    mine_from_repo_hints,
    practice_from_one_offs,
    propose_parallelise,
    propose_serialise,
    recertify_stale,
    schedule_shadow_evaluations,
)
from recertia.ledger import HashChainLedger
from recertia.memory.procedural.active_set import recompute_active_set
from recertia.memory.procedural.composition import mean_composition_depth
from recertia.memory.procedural.promote import PromotionError, promote_to_approved
from recertia.memory.procedural.store import SkillStore
from recertia.proposals.store import ProposalRecord, ProposalStore
from recertia.review.autonomy_config import DEFAULT_AUTONOMY
from recertia.solver.transcript import TranscriptStore
from recertia.trajectory.store import TrajectoryStore
from recertia.workers.run_worker import AsyncRunWorker


class GoalPreview(BaseModel):
    goal: Goal


class DevLogin(BaseModel):
    user_id: str = "dev-operator"
    display_name: str = "Dev Operator"
    roles: list[str] = Field(default_factory=lambda: ["operator", "reviewer", "admin"])
    tenants: list[str] = Field(default_factory=lambda: ["default"])
    active_tenant: str | None = None


class ProposalDecision(BaseModel):
    decision: Literal["approve", "reject", "request_changes"]
    note: str = ""


class JobTrigger(BaseModel):
    dry_run: bool = True
    max_proposals: int = 10
    hint: list[str] | None = None
    one_off: list[str] | None = None
    skill_id: str | None = None
    skill_version: int = 1
    fake_edge_failures: int = 0
    merge_conflicts: int = 0
    tool_upgraded: str | None = None


class TenantSwitch(BaseModel):
    tenant_id: str


class ConsoleContext:
    def __init__(
        self,
        *,
        root: Path,
        skills_root: Path,
        facts_root: Path,
        key_store: Any,
        quota_store: QuotaStore,
        runs: dict,
        run_slots: threading.Semaphore,
        record_from_state: Any,
        load_from_checkpoints: Any,
        resolve_create_workdir: Any,
        persist_workdir: Any,
        canonical_run_workdir: Any,
        clamp_criteria: Any,
        principal_may_exec: Any,
        require_scope: Any,
        validate_run_id: Any,
    ) -> None:
        self.root = root
        self.skills_root = skills_root
        self.facts_root = facts_root
        self.key_store = key_store
        self.quota_store = quota_store
        self.runs = runs
        self.run_slots = run_slots
        self.record_from_state = record_from_state
        self.load_from_checkpoints = load_from_checkpoints
        self.resolve_create_workdir = resolve_create_workdir
        self.persist_workdir = persist_workdir
        self.canonical_run_workdir = canonical_run_workdir
        self.clamp_criteria = clamp_criteria
        self.principal_may_exec = principal_may_exec
        self.require_scope = require_scope
        self.validate_run_id = validate_run_id
        self.sessions = SessionStore()
        self.proposals = ProposalStore(root / "proposals.sqlite")
        self.job_runs = JobRunStore(root / "job_runs.sqlite")
        self.events = RunEventLog(root / "run_events")
        self.worker = AsyncRunWorker(
            events=self.events,
            on_complete=self._on_async_complete,
            on_failed=self._on_async_failed,
        )
        self._cancel_flags: set[str] = set()

    def tenant_skills_root(self, tenant_id: str) -> Path:
        if os.environ.get("RECERTIA_TENANT_SKILLS", "").strip() in {"1", "true", "yes"}:
            path = self.root / "tenants" / tenant_id / "skills"
            path.mkdir(parents=True, exist_ok=True)
            return path
        return self.skills_root

    def tenant_runs_root(self, tenant_id: str) -> Path:
        return self.root / "runs" / tenant_id

    def _on_async_complete(self, tenant_id: str, run_id: str, state: Any) -> None:
        cost = float(state.spent.cost_usd or 0.0)
        existing = self.runs.get((tenant_id, run_id))
        rec = self.record_from_state(
            run_id=run_id,
            request=state.task.request,
            task_class=state.task.task_class or "repo-chore",
            tenant_id=tenant_id,
            state=state,
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
            has_goal=state.task.goal is not None,
        )
        self.runs[(tenant_id, run_id)] = rec.model_copy(
            update={"cost_usd": cost, "mode": "async"}
        )
        self.quota_store.complete(tenant_id, cost_usd=cost)

    def _on_async_failed(self, tenant_id: str, run_id: str, *, cancelled: bool = False) -> None:
        self.quota_store.release_inflight(tenant_id)
        existing = self.runs.get((tenant_id, run_id))
        if existing is None:
            return
        terminal = "cancelled" if cancelled else "error"
        self.runs[(tenant_id, run_id)] = existing.model_copy(
            update={"status": terminal, "terminal": terminal, "mode": "async"}
        )


def register_console_routes(app: FastAPI, ctx: ConsoleContext) -> None:
    require_runs = ctx.require_scope("runs", ctx.key_store)
    require_metrics = ctx.require_scope("metrics", ctx.key_store)

    def _optional_console_user(request: Request) -> ConsoleUser | None:
        token = request.headers.get("X-Recertia-Session") or request.cookies.get(
            "recertia_session"
        )
        return ctx.sessions.parse(token)

    def _resolve_tenant(
        principal: Any,
        request: Request,
        x_recertia_tenant: str | None,
    ) -> str:
        """API keys are single-tenant; console sessions may switch among memberships (C5)."""

        user = _optional_console_user(request)
        if x_recertia_tenant:
            if user is not None:
                if x_recertia_tenant not in user.tenants:
                    raise HTTPException(status_code=403, detail="tenant not in membership")
                return x_recertia_tenant
            if x_recertia_tenant != principal.tenant_id:
                raise HTTPException(status_code=403, detail="api key tenant mismatch")
            return x_recertia_tenant
        if user is not None:
            return user.active_tenant
        return principal.tenant_id

    # ----- C3 auth -----
    @app.get("/v1/me")
    def me(request: Request) -> dict[str, Any]:
        user = _optional_console_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="console authentication required")
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "roles": sorted(user.roles),
            "tenants": list(user.tenants),
            "active_tenant": user.active_tenant,
            "auth_mode": auth_mode(),
        }

    @app.post("/v1/auth/dev-login")
    def dev_login(body: DevLogin, response: Response) -> dict[str, Any]:
        if auth_mode() not in {"dev", "development"}:
            raise HTTPException(status_code=404, detail="dev login disabled")
        tenants = tuple(body.tenants) or ("default",)
        active = body.active_tenant or tenants[0]
        user = ConsoleUser(
            user_id=body.user_id,
            display_name=body.display_name,
            roles=frozenset(body.roles) or frozenset({"operator"}),
            tenants=tenants,
            active_tenant=active if active in tenants else tenants[0],
        )
        token = ctx.sessions.issue(user)
        response.set_cookie("recertia_session", token, httponly=True, samesite="lax")
        return {"session": token, "user": json.loads(json.dumps({
            "user_id": user.user_id,
            "display_name": user.display_name,
            "roles": sorted(user.roles),
            "tenants": list(user.tenants),
            "active_tenant": user.active_tenant,
        }))}

    @app.post("/v1/auth/logout")
    def logout(response: Response) -> dict[str, str]:
        response.delete_cookie("recertia_session")
        return {"status": "ok"}

    @app.post("/v1/auth/switch-tenant")
    def switch_tenant(body: TenantSwitch, request: Request, response: Response) -> dict[str, Any]:
        user = _optional_console_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="console authentication required")
        try:
            switched = ctx.sessions.switch_tenant(user, body.tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        token = ctx.sessions.issue(switched)
        response.set_cookie("recertia_session", token, httponly=True, samesite="lax")
        return {"active_tenant": switched.active_tenant, "session": token, "tenants": list(switched.tenants)}

    @app.get("/v1/auth/oidc/login")
    def oidc_login(request: Request) -> dict[str, str]:
        if auth_mode() != "oidc" or not oidc_configured():
            raise HTTPException(status_code=404, detail="oidc not configured")
        redirect = str(request.url_for("oidc_callback"))
        state = uuid4().hex
        return {"authorize_url": oidc_authorize_url(redirect_uri=redirect, state=state), "state": state}

    @app.get("/v1/auth/oidc/callback", name="oidc_callback")
    def oidc_callback(
        request: Request, response: Response, code: str = "", state: str = ""
    ) -> dict[str, Any]:
        del state
        if auth_mode() != "oidc" or not oidc_configured():
            raise HTTPException(status_code=404, detail="oidc not configured")
        redirect = str(request.url_for("oidc_callback"))
        user = oidc_exchange_code(code=code, redirect_uri=redirect)
        token = ctx.sessions.issue(user)
        response.set_cookie("recertia_session", token, httponly=True, samesite="lax")
        return {"session": token, "user_id": user.user_id, "tenants": list(user.tenants)}

    # ----- C0 goals / templates -----
    @app.post("/v1/goals/preview")
    def goals_preview(body: GoalPreview, principal=Depends(require_runs)) -> dict[str, Any]:
        del principal
        criteria = compile_goal(body.goal)
        return {
            "goal": body.goal.model_dump(mode="json"),
            "criteria": [c.model_dump(mode="json") for c in criteria],
        }

    @app.get("/v1/templates")
    def templates(principal=Depends(require_runs)) -> dict[str, Any]:
        del principal
        return {"templates": list_templates()}

    @app.get("/v1/templates/{template_id}")
    def template_detail(template_id: str, principal=Depends(require_runs)) -> dict[str, Any]:
        del principal
        try:
            goal = get_template_goal(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template not found") from exc
        return {"id": template_id, "goal": goal.model_dump(mode="json")}

    # ----- C0 runs list / transcript / trajectory -----
    @app.get("/v1/runs")
    def list_runs(
        request: Request,
        principal=Depends(require_runs),
        task_class: str | None = None,
        terminal: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        orch = GraphOrchestrator(ctx.tenant_runs_root(tenant_id))
        try:
            ids = orch.checkpoints.list_run_ids()
        finally:
            orch.close()
        # Also include in-memory runs for this tenant.
        mem_ids = [rid for (tid, rid) in ctx.runs if tid == tenant_id]
        all_ids = sorted(set(ids) | set(mem_ids))
        if cursor:
            all_ids = [i for i in all_ids if i > cursor]
        items: list[dict[str, Any]] = []
        for run_id in all_ids:
            if len(items) >= limit:
                break
            rec = ctx.runs.get((tenant_id, run_id)) or ctx.load_from_checkpoints(
                ctx.root, tenant_id, run_id
            )
            if rec is None:
                continue
            if task_class and rec.task_class != task_class:
                continue
            if terminal and (rec.terminal or "") != terminal:
                continue
            # PC-1: never leak other tenants — record carries tenant_id
            if rec.tenant_id != tenant_id:
                continue
            items.append(
                {
                    "run_id": rec.run_id,
                    "task_class": rec.task_class,
                    "terminal": rec.terminal,
                    "status": rec.status,
                    "attempt_no": rec.attempt_no,
                    "created_at": rec.created_at.isoformat()
                    if hasattr(rec.created_at, "isoformat")
                    else rec.created_at,
                    "cost_usd": getattr(rec, "cost_usd", None),
                    "arm": rec.arm,
                    "tenant_id": rec.tenant_id,
                }
            )
        next_cursor = items[-1]["run_id"] if items and len(items) == limit else None
        return {"items": items, "next_cursor": next_cursor}

    @app.get("/v1/runs/{run_id}/transcript")
    def run_transcript(
        run_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        run_id = ctx.validate_run_id(run_id)
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        orch = GraphOrchestrator(ctx.tenant_runs_root(tenant_id))
        try:
            latest = orch.checkpoints.latest(run_id)
            if latest is None:
                raise HTTPException(status_code=404, detail="run not found")
            state = latest[3]
        finally:
            orch.close()
        ref = state.transcript_ref
        store = TranscriptStore(ctx.tenant_runs_root(tenant_id) / "transcripts")
        if not ref:
            return {"run_id": run_id, "events": [], "content_hash": None}
        try:
            payload = store.read(ref)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="transcript not found") from exc
        return {"run_id": run_id, "content_hash": ref, **payload}

    @app.get("/v1/runs/{run_id}/trajectory")
    def run_trajectory(
        run_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        run_id = ctx.validate_run_id(run_id)
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        store = TrajectoryStore(ctx.tenant_runs_root(tenant_id) / "trajectories")
        traj = store.get_trajectory(run_id)
        if traj is None:
            raise HTTPException(status_code=404, detail="trajectory not found")
        return traj.model_dump(mode="json")

    # ----- C2 async / events / cancel -----
    @app.get("/v1/runs/{run_id}/events")
    def run_events(
        run_id: str,
        request: Request,
        principal=Depends(require_runs),
        after: str | None = None,
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> StreamingResponse:
        run_id = ctx.validate_run_id(run_id)
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        rec = ctx.runs.get((tenant_id, run_id)) or ctx.load_from_checkpoints(
            ctx.root, tenant_id, run_id
        )
        if rec is None and not (ctx.root / "run_events" / f"{run_id}.jsonl").exists():
            raise HTTPException(status_code=404, detail="run not found")

        def gen():
            yield from ctx.events.iter_sse(run_id, after=after)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel_run(
        run_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        del x_recertia_tenant, request
        run_id = ctx.validate_run_id(run_id)
        ctx.worker.request_cancel(run_id)
        ctx.events.append(run_id, "run.cancelled", {"by": principal.key_id})
        return {"run_id": run_id, "status": "cancel_requested"}

    # ----- C0 skills -----
    @app.get("/v1/skills")
    def list_skills(
        request: Request,
        principal=Depends(require_runs),
        task_class: str | None = None,
        lifecycle: str | None = None,
        active: bool | None = None,
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        store = SkillStore(ctx.tenant_skills_root(tenant_id))
        items = []
        for ver, status, stats in store.iter_loaded():
            if task_class and ver.task_class != task_class:
                continue
            if lifecycle and status.lifecycle != lifecycle:
                continue
            if active is not None and status.active != active:
                continue
            items.append(
                {
                    "skill_id": ver.skill_id,
                    "version": ver.version,
                    "title": ver.title,
                    "task_class": ver.task_class,
                    "lifecycle": status.lifecycle,
                    "active": status.active,
                    "contribution": stats.contribution.model_dump(mode="json")
                    if stats.contribution
                    else None,
                }
            )
        return {"items": items}

    @app.get("/v1/skills/{skill_id}/versions/{version}")
    def skill_version(
        skill_id: str,
        version: int,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        store = SkillStore(ctx.tenant_skills_root(tenant_id))
        try:
            ver = store.get_version(skill_id, version)
            status = store.get_status(skill_id, version)
            stats = store.get_stats(skill_id, version)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="skill not found") from exc
        return {
            "version": ver.model_dump(mode="json"),
            "status": status.model_dump(mode="json"),
            "stats": stats.model_dump(mode="json"),
        }

    @app.post("/v1/skills/search")
    def skills_search(
        payload: dict[str, Any],
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        query = str(payload.get("query") or "")
        limit = int(payload.get("limit") or 5)
        store = SkillStore(ctx.tenant_skills_root(tenant_id))
        index_path = ctx.tenant_runs_root(tenant_id) / "skill_index.db"
        from recertia.retrieval.index import SkillIndex

        index = SkillIndex(index_path)
        try:
            entries = list(store.iter_loaded())
            index.rebuild(entries, library_fingerprint=store.library_fingerprint())
            hits = index.lexical_top_k(query, limit)
        finally:
            if hasattr(index, "close"):
                index.close()  # type: ignore[attr-defined]
        return {
            "query": query,
            "hits": [
                {"skill_id": sid, "version": ver, "score": score} for sid, ver, score in hits
            ],
        }

    @app.post("/v1/skills/{skill_id}/versions/{version}/promote")
    def promote_skill(
        skill_id: str,
        version: int,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        user = _optional_console_user(request)
        if user is not None and not user.may("reviewer"):
            raise HTTPException(status_code=403, detail="requires reviewer role")
        job = ctx.job_runs.create(
            "promote",
            tenant_id=tenant_id,
            dry_run=False,
            meta={"skill_id": skill_id, "version": version},
        )
        job.status = "running"
        ctx.job_runs.save(job)
        store = SkillStore(ctx.tenant_skills_root(tenant_id))
        runs_root = ctx.tenant_runs_root(tenant_id)
        log_dir = runs_root / "promotion_logs"
        try:
            status = promote_to_approved(
                store,
                skill_id,
                version,
                golden_root=Path("evals/golden"),
                runs_root=runs_root,
                log_dir=log_dir,
                require_task_class_gate=False,
                golden_dir=Path("evals/golden") / "repo-chore" / skill_id,
            )
            if status.lifecycle != "approved":
                raise PromotionError(
                    f"promote refused: lifecycle={status.lifecycle!r} (golden gate required)"
                )
            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.meta["lifecycle"] = status.lifecycle
        except PromotionError as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.meta["failing_fixtures"] = list(exc.failing_fixtures)
            ctx.job_runs.save(job)
            return {
                "job_run_id": job.job_run_id,
                "status": "failed",
                "error": str(exc),
                "failing_fixtures": list(exc.failing_fixtures),
            }
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc).isoformat()
            ctx.job_runs.save(job)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ctx.job_runs.save(job)
        ledger = HashChainLedger(runs_root / "ledger.jsonl")
        ledger.append(
            actor=(user.user_id if user else principal.key_id),
            action="policy_change",
            target=f"skill:{skill_id}@v{version}",
            evidence={"kind": "console_promote", "job_run_id": job.job_run_id},
        )
        return {"job_run_id": job.job_run_id, "status": "succeeded", "lifecycle": "approved"}

    # ----- C0 metrics -----
    @app.get("/v1/metrics/report")
    def metrics_report(
        request: Request,
        principal=Depends(require_metrics),
        task_class: str = "repo-chore",
        snapshot_id: str | None = None,
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        eval_db = ctx.tenant_runs_root(tenant_id) / "evals.db"
        store = EvalStore(eval_db)
        try:
            rows = store.metric_rows(task_class=task_class, snapshot_id=snapshot_id)
            snap = snapshot_id or (rows[0]["snapshot_id"] if rows else "none")
            skill_store = SkillStore(ctx.tenant_skills_root(tenant_id))
            _u, pressure = recompute_active_set(skill_store, config=DEFAULT_AUTONOMY)
            mean_pressure = sum(pressure.values()) / len(pressure) if pressure else 0.0
            canary = run_judge_canary()
            report = build_metric_report(
                rows,
                snapshot_id=snap,
                task_class=task_class,
                active_cap_pressure=mean_pressure,
                judge_false_pass_rate=canary.false_pass_rate,
                mean_composition_depth=mean_composition_depth(skill_store),
            )
        finally:
            store.close()
        return report.model_dump(mode="json")

    @app.get("/v1/metrics/canary")
    def metrics_canary(principal=Depends(require_metrics)) -> dict[str, Any]:
        del principal
        report = run_judge_canary()
        return {
            "trials": report.trials,
            "false_passes": report.false_passes,
            "false_pass_rate": report.false_pass_rate,
            "model_version": report.model_version,
        }

    @app.get("/v1/ledger/verify")
    def ledger_verify(
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        path = ctx.tenant_runs_root(tenant_id) / "ledger.jsonl"
        ledger = HashChainLedger(path)
        try:
            ledger.verify()
            return {"ok": True, "entries": len(ledger.entries())}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # ----- C1 proposals / jobs -----
    @app.get("/v1/proposals")
    def list_proposals(
        request: Request,
        principal=Depends(require_runs),
        status: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        items = ctx.proposals.list(
            tenant_id=tenant_id, status=status, kind=kind, limit=limit
        )
        return {"items": [p.to_dict() for p in items]}

    @app.get("/v1/proposals/{proposal_id}")
    def get_proposal(
        proposal_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        rec = ctx.proposals.get(proposal_id, tenant_id=tenant_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        return rec.to_dict()

    @app.post("/v1/proposals/{proposal_id}/decision")
    def decide_proposal(
        proposal_id: str,
        body: ProposalDecision,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        user = _optional_console_user(request)
        rec = ctx.proposals.get(proposal_id, tenant_id=tenant_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if rec.kind in {"correction"} or rec.payload.get("tier") == "T2":
            if user is not None and not user.may("reviewer"):
                raise HTTPException(status_code=403, detail="T2 requires reviewer")
            if user is None and "admin" not in principal.scopes:
                raise HTTPException(status_code=403, detail="T2 requires admin key or reviewer")
        actor = user.user_id if user else principal.key_id
        try:
            updated = ctx.proposals.decide(
                proposal_id,
                tenant_id=tenant_id,
                decision=body.decision,
                actor=actor,
                note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ledger = HashChainLedger(ctx.tenant_runs_root(tenant_id) / "ledger.jsonl")
        ledger.append(
            actor=actor,
            action="policy_change",
            target=f"proposal:{proposal_id}",
            evidence={
                "kind": "proposal_decision",
                "decision": body.decision,
                "note": body.note,
                "proposal_kind": rec.kind,
            },
        )
        return updated.to_dict()

    @app.get("/v1/jobs")
    def list_jobs(
        request: Request,
        principal=Depends(require_runs),
        limit: int = 50,
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        return {
            "items": [j.to_dict() for j in ctx.job_runs.list(tenant_id=tenant_id, limit=limit)]
        }

    @app.get("/v1/jobs/{job_run_id}")
    def get_job(
        job_run_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        rec = ctx.job_runs.get(job_run_id, tenant_id=tenant_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="job not found")
        return rec.to_dict()

    @app.post("/v1/jobs/{job}/run")
    def trigger_job(
        job: str,
        body: JobTrigger,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        name = job.strip().lower()
        store = SkillStore(ctx.tenant_skills_root(tenant_id))
        runs_root = ctx.tenant_runs_root(tenant_id)
        runner = JobRunner(store, runs_root=runs_root / "jobs")
        budget = JobBudget(max_proposals=body.max_proposals)
        job_rec = ctx.job_runs.create(
            name, tenant_id=tenant_id, dry_run=body.dry_run
        )
        job_rec.status = "running"
        ctx.job_runs.save(job_rec)
        traj = TrajectoryStore(runs_root / "trajectories")
        try:
            if name in {"mine", "miner"}:
                hints = list(body.hint or ["README.md chore hints"])
                result = runner.run(
                    "mine", lambda: mine_from_repo_hints(store, hints=hints), budget=budget
                )
            elif name in {"curator", "curate"}:
                result = runner.run(
                    "curator",
                    lambda: curator_active_set_and_dedup(store, trajectory_store=traj),
                    budget=budget,
                )
            elif name == "practice":
                reasons = list(body.one_off) if body.one_off else load_one_off_reasons(
                    runs_root / "one_off_log.jsonl"
                )
                if not reasons:
                    reasons = ["unsolved one-off cluster"]
                curriculum = None if body.dry_run else runs_root / "practice-curriculum"
                result = runner.run(
                    "practice",
                    lambda: practice_from_one_offs(reasons, curriculum_dir=curriculum),
                    budget=budget,
                )
            elif name == "recertify":
                result = runner.run(
                    "recertify",
                    lambda: recertify_stale(store, tool_upgraded=body.tool_upgraded),
                    budget=budget,
                )
            elif name == "shadow":
                result = runner.run(
                    "shadow", lambda: schedule_shadow_evaluations(store), budget=budget
                )
            elif name in {"parallelise", "parallelize"}:
                if not body.skill_id:
                    raise HTTPException(status_code=400, detail="skill_id required")
                result = runner.run(
                    "parallelise",
                    lambda: propose_parallelise(
                        body.skill_id,  # type: ignore[arg-type]
                        body.skill_version,
                        fake_edge_failures=body.fake_edge_failures or None,
                    ),
                    budget=budget,
                )
            elif name in {"serialise", "serialize"}:
                if not body.skill_id:
                    raise HTTPException(status_code=400, detail="skill_id required")
                result = runner.run(
                    "serialise",
                    lambda: propose_serialise(
                        body.skill_id,  # type: ignore[arg-type]
                        body.skill_version,
                        merge_conflict_count=body.merge_conflicts or None,
                    ),
                    budget=budget,
                )
            elif name in {"correction", "correction_miner"}:
                edits = load_reviewer_edits(runs_root / "reviewer_edits.jsonl")
                result = runner.run(
                    "correction",
                    lambda: correction_miner_from_reviewer_edits(edits),
                    budget=budget,
                )
            else:
                raise HTTPException(status_code=404, detail=f"unknown job {job}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            job_rec.status = "failed"
            job_rec.error = str(exc)
            job_rec.finished_at = datetime.now(timezone.utc).isoformat()
            ctx.job_runs.save(job_rec)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        persisted = []
        for p in result.proposals:
            rec = ProposalRecord(
                proposal_id=uuid4().hex[:12],
                kind=p.kind,
                skill_id=p.skill_id,
                version=p.version,
                rationale=p.rationale,
                payload=p.payload,
                tenant_id=tenant_id,
                created_by_job=job_rec.job_run_id,
            )
            if not body.dry_run:
                ctx.proposals.add(rec)
            persisted.append(rec.to_dict())
        job_rec.status = "succeeded"
        job_rec.proposals = persisted
        job_rec.finished_at = datetime.now(timezone.utc).isoformat()
        ctx.job_runs.save(job_rec)
        return job_rec.to_dict()

    @app.get("/v1/console/tower-summary")
    def tower_summary(
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        """C4: practice conversion + active cap pressure for Tower panels."""

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        skill_store = SkillStore(ctx.tenant_skills_root(tenant_id))
        _u, pressure = recompute_active_set(skill_store, config=DEFAULT_AUTONOMY)
        mean_pressure = sum(pressure.values()) / len(pressure) if pressure else 0.0
        eval_db = ctx.tenant_runs_root(tenant_id) / "evals.db"
        practice_conversion = None
        unavailable = None
        if eval_db.exists():
            store = EvalStore(eval_db)
            try:
                rows = store.metric_rows()
                report = build_metric_report(
                    rows,
                    snapshot_id="tower",
                    active_cap_pressure=mean_pressure,
                    mean_composition_depth=mean_composition_depth(skill_store),
                )
                practice_conversion = report.practice_conversion
                unavailable = report.unavailable.get("practice_conversion")
            finally:
                store.close()
        pending = ctx.proposals.list(tenant_id=tenant_id, status="pending", limit=100)
        return {
            "active_cap_pressure": mean_pressure,
            "pressure_by_class": pressure,
            "mean_composition_depth": mean_composition_depth(skill_store),
            "practice_conversion": practice_conversion,
            "practice_conversion_unavailable": unavailable,
            "pending_proposals": len(pending),
        }

    # Expose async create helper used by patched POST /v1/runs
    app.state.console_ctx = ctx
