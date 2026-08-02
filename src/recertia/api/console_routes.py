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
from contracts.program import ExternalHandoff, MigrationProgram, MigrationStep, RepoBinding
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
from recertia.console_compose import suggest_criteria
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
from recertia.programs.materialize import (
    MaterializeError,
    assert_gp0_execution_prereqs,
    materialize_step_goal,
    preview_hash,
    previous_step,
    resolve_run_budget,
    step_is_ready,
)
from recertia.programs.store import ProgramStore
from recertia.programs.stress import stress_program, stress_step
from recertia.proposals.store import ProposalRecord, ProposalStore
from recertia.review.autonomy_config import DEFAULT_AUTONOMY
from recertia.solver.transcript import TranscriptStore
from recertia.trajectory.store import TrajectoryStore
from recertia.workers.run_worker import AsyncRunWorker


class GoalPreview(BaseModel):
    goal: Goal


class GoalSuggest(BaseModel):
    context: str = Field(min_length=1)
    task_class: str = "repo-chore"
    use_model: bool = True


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


class ProgramCreate(BaseModel):
    title: str
    intent: str = ""
    task_class: str = "repo-chore"
    decomposition: Literal["by_risk", "by_layer", "by_seam", "custom"] = "custom"
    handoff: Literal["none", "operator_workdir", "copy_forward", "git_tip"] = "none"
    freeze_enforcement: Literal["advisory", "hard"] = "advisory"
    steps: list[dict[str, Any]] = Field(default_factory=list)
    program_bar_desired: list[dict[str, Any]] = Field(default_factory=list)
    program_bar_constraints: list[dict[str, Any]] = Field(default_factory=list)
    source: Literal["human", "heuristic", "model", "template"] = "human"


class ProgramFromPack(BaseModel):
    title: str
    intent: str = ""
    task_class: str = "repo-chore"
    decomposition: Literal["by_risk", "by_layer", "by_seam", "custom"] = "by_risk"
    steps: list[dict[str, Any]] = Field(min_length=1)


class ProgramAccept(BaseModel):
    ack_disclaimer: bool = True


class RepoBindingBody(BaseModel):
    root: str = Field(min_length=1)
    binding_id: str = "default"
    default_branch: str = "main"
    remote_url: str | None = None


class RecordTipBody(BaseModel):
    """Record HEAD from a path under tenant workspaces or the binding root."""

    workdir: str | None = None
    use_binding_root: bool = False


class SeedWorkdirBody(BaseModel):
    run_id: str
    tip_sha: str | None = None


class GoalProbe(BaseModel):
    workdir: str = Field(min_length=1, description="Relative workdir under tenant workspace root")


class StepPatch(BaseModel):
    title: str | None = None
    goal: Goal | None = None
    freeze_paths: list[str] | None = None
    mutate_paths: list[str] | None = None
    role: Literal["characterization", "structural", "behaviour_lock", "custom"] | None = None
    external_handoff: ExternalHandoff | None = None


class StepSkipBody(BaseModel):
    note: str


class StepRunBody(BaseModel):
    plan_only: bool = False
    workdir: str | None = None
    budget: dict[str, Any] | None = None
    bind_run_id: str | None = None
    idempotency_key: str | None = None


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
        self.programs = ProgramStore(root / "programs.sqlite")
        self.job_runs = JobRunStore(root / "job_runs.sqlite")
        self._program_idempotency: dict[str, str] = {}
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

    @app.post("/v1/goals/suggest")
    def goals_suggest(body: GoalSuggest, principal=Depends(require_runs)) -> dict[str, Any]:
        """Pilot Compose: draft desired states (never locks criteria)."""

        del principal
        result = suggest_criteria(
            context=body.context,
            task_class=body.task_class or "repo-chore",
            use_model=body.use_model,
        )
        payload = result.to_dict()
        payload["blocked"] = any(w["severity"] == "block" for w in payload["warnings"])
        return payload

    @app.post("/v1/goals/probe")
    def goals_probe(
        body: GoalProbe,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        """Read-only inventory assist for Compose / programs (never locks criteria)."""

        from recertia.programs.probe import probe_workdir

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        rel = body.workdir.strip().lstrip("/")
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            raise HTTPException(status_code=400, detail="workdir must be relative")
        root = (ctx.root / "workspaces" / tenant_id / rel).resolve()
        try:
            root.relative_to((ctx.root / "workspaces" / tenant_id).resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="workdir escapes tenant root") from exc
        return {"probe": probe_workdir(root), "locked": False}

    @app.post("/v1/programs/from-pack")
    def program_from_pack(
        body: ProgramFromPack,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        """Accept a Compose decomposition/pack draft into a durable MigrationProgram."""

        from contracts.goal import Constraint, DesiredState

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        steps: list[MigrationStep] = []
        for i, raw in enumerate(body.steps):
            desired_raw = raw.get("desired") or []
            # Ensure each step Goal has ≥1 hard desired
            if not desired_raw:
                desired_raw = [
                    {
                        "id": f"step-{i}-placeholder",
                        "kind": "file_exists",
                        "path": "README.md",
                        "weight": 1.0,
                    }
                ]
            # Strip draft-only fields
            desired = []
            for d in desired_raw:
                clean = {k: v for k, v in d.items() if k in DesiredState.model_fields}
                desired.append(DesiredState.model_validate(clean))
            constraints = []
            for c in raw.get("constraints") or []:
                clean = {k: v for k, v in c.items() if k in Constraint.model_fields}
                constraints.append(Constraint.model_validate(clean))
            goal = Goal(
                desired=desired,
                constraints=constraints,
                context=raw.get("context"),
                task_class=body.task_class,
            )
            role_raw = raw.get("role")
            role: Literal[
                "characterization", "structural", "behaviour_lock", "custom"
            ] = (
                role_raw
                if role_raw
                in {"characterization", "structural", "behaviour_lock", "custom"}
                else "custom"
            )
            steps.append(
                MigrationStep(
                    step_id=raw.get("step_id") or f"s{i}",
                    ordinal=int(raw.get("ordinal", i)),
                    title=raw.get("title") or f"Step {i}",
                    role=role,
                    goal=goal,
                    freeze_paths=list(raw.get("freeze_paths") or []),
                    mutate_paths=list(raw.get("mutate_paths") or []),
                )
            )
        prog = MigrationProgram(
            program_id=uuid4().hex[:12],
            tenant_id=tenant_id,
            title=body.title,
            intent=body.intent,
            task_class=body.task_class,
            decomposition=body.decomposition,
            steps=steps,
            source="heuristic",
            status="draft",
            created_by=str(getattr(principal, "key_id", "") or ""),
        )
        saved = ctx.programs.put(prog)
        return {
            "program": saved.model_dump(mode="json"),
            "warnings": [w.to_dict() for w in stress_program(saved)],
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

    def _refresh_step_statuses(prog: MigrationProgram) -> MigrationProgram:
        steps = []
        for step in prog.steps:
            updated = step
            if (
                step.current_run_id
                and step.status in {"queued", "running"}
            ):
                rec = ctx.runs.get((prog.tenant_id, step.current_run_id))
                if rec is not None:
                    terminal = rec.terminal or rec.status
                    gate = step.acceptance_gate.terminal_in
                    if terminal in gate:
                        new_status = "succeeded"
                    elif terminal in {"queued"} or rec.status == "queued":
                        new_status = "queued"
                    elif terminal in {"running"} or rec.status == "running":
                        new_status = "running"
                    elif terminal:
                        new_status = "failed"
                    else:
                        new_status = step.status
                    if new_status != step.status:
                        updated = step.model_copy(update={"status": new_status})
            if updated.status == "planned" and step_is_ready(prog, updated):
                updated = updated.model_copy(update={"status": "ready"})
            steps.append(updated)
        refreshed = prog.model_copy(update={"steps": steps})
        # Recompute pack status from step terminals
        if refreshed.status in {"active", "blocked"}:
            if any(s.status == "failed" for s in refreshed.steps):
                refreshed = refreshed.model_copy(update={"status": "blocked"})
            elif refreshed.steps and all(
                s.status in {"succeeded", "skipped"} for s in refreshed.steps
            ):
                refreshed = refreshed.model_copy(update={"status": "completed"})
            elif refreshed.status == "blocked" and not any(
                s.status == "failed" for s in refreshed.steps
            ):
                refreshed = refreshed.model_copy(update={"status": "active"})
        # Second pass: planned→ready after predecessor may have just succeeded
        steps2 = []
        for step in refreshed.steps:
            if step.status == "planned" and step_is_ready(refreshed, step):
                steps2.append(step.model_copy(update={"status": "ready"}))
            else:
                steps2.append(step)
        return refreshed.model_copy(update={"steps": steps2})

    def _assert_freeze_allowed(enforcement: str) -> None:
        from recertia.programs.materialize import assert_freeze_enforcement_allowed

        try:
            assert_freeze_enforcement_allowed(enforcement)
        except MaterializeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _get_program(program_id: str, tenant_id: str) -> MigrationProgram:
        prog = ctx.programs.get(program_id, tenant_id=tenant_id)
        if prog is None:
            raise HTTPException(status_code=404, detail="program not found")
        return prog

    def _find_step(prog: MigrationProgram, step_id: str) -> MigrationStep:
        for step in prog.steps:
            if step.step_id == step_id:
                return step
        raise HTTPException(status_code=404, detail="step not found")

    def _replace_step(prog: MigrationProgram, updated: MigrationStep) -> MigrationProgram:
        steps = [updated if s.step_id == updated.step_id else s for s in prog.steps]
        return prog.model_copy(update={"steps": steps})

    # ----- GP0 migration programs (Goal packs) -----
    @app.post("/v1/programs")
    def create_program(
        request: Request,
        body: ProgramCreate,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        from contracts.goal import Constraint, DesiredState

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        _assert_freeze_allowed(body.freeze_enforcement)
        steps = [MigrationStep.model_validate(s) for s in body.steps]
        prog = MigrationProgram(
            program_id=uuid4().hex[:12],
            tenant_id=tenant_id,
            title=body.title,
            intent=body.intent,
            task_class=body.task_class,
            decomposition=body.decomposition,
            handoff=body.handoff,
            freeze_enforcement=body.freeze_enforcement,
            steps=steps,
            program_bar_desired=[DesiredState.model_validate(d) for d in body.program_bar_desired],
            program_bar_constraints=[
                Constraint.model_validate(c) for c in body.program_bar_constraints
            ],
            source=body.source,
            created_by=str(getattr(principal, "key_id", "") or ""),
            status="draft",
        )
        saved = ctx.programs.put(prog)
        return {
            "program": saved.model_dump(mode="json"),
            "warnings": [w.to_dict() for w in stress_program(saved)],
        }

    @app.get("/v1/programs")
    def list_programs(
        request: Request,
        status: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        items = ctx.programs.list(tenant_id=tenant_id, status=status, limit=limit)
        return {"programs": [p.model_dump(mode="json") for p in items]}

    @app.get("/v1/programs/{program_id}")
    def get_program(
        program_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _refresh_step_statuses(_get_program(program_id, tenant_id))
        ctx.programs.put(prog)
        return {
            "program": prog.model_dump(mode="json"),
            "warnings": [w.to_dict() for w in stress_program(prog)],
        }

    @app.post("/v1/programs/{program_id}/accept")
    def accept_program(
        program_id: str,
        body: ProgramAccept,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        if not body.ack_disclaimer:
            raise HTTPException(status_code=400, detail="disclaimer must be acknowledged")
        prog = _get_program(program_id, tenant_id)
        _assert_freeze_allowed(prog.freeze_enforcement)
        if prog.status != "draft":
            raise HTTPException(status_code=409, detail="only draft programs can be accepted")
        if not prog.steps:
            raise HTTPException(status_code=400, detail="program has no steps")
        if prog.handoff == "git_tip" and prog.repo_binding is None:
            raise HTTPException(
                status_code=400,
                detail="handoff=git_tip requires a registered repo_binding before accept",
            )
        if prog.handoff == "copy_forward":
            raise HTTPException(
                status_code=400,
                detail="handoff=copy_forward is not supported; use git_tip",
            )
        for step in prog.steps:
            # Goal validation already ensures hard criteria
            if not step.goal.desired:
                raise HTTPException(status_code=400, detail=f"step {step.step_id} missing goal")
        now = datetime.now(timezone.utc).isoformat()
        prog = prog.model_copy(
            update={"status": "active", "disclaimer_acked_at": now}
        )
        prog = _refresh_step_statuses(prog)
        saved = ctx.programs.put(prog)
        return {"program": saved.model_dump(mode="json")}

    @app.post("/v1/programs/{program_id}/abandon")
    def abandon_program(
        program_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _get_program(program_id, tenant_id)
        saved = ctx.programs.put(prog.model_copy(update={"status": "abandoned"}))
        return {"program": saved.model_dump(mode="json")}

    @app.patch("/v1/programs/{program_id}/steps/{step_id}")
    def patch_step(
        program_id: str,
        step_id: str,
        body: StepPatch,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _get_program(program_id, tenant_id)
        step = _find_step(prog, step_id)
        if step.status in {"queued", "running", "succeeded"}:
            raise HTTPException(
                status_code=409,
                detail="step goal is immutable after run bind / success",
            )
        updates: dict[str, Any] = {}
        if body.title is not None:
            updates["title"] = body.title
        if body.goal is not None:
            updates["goal"] = body.goal
            updates["goal_revision"] = step.goal_revision + 1
            updates["criteria_preview_hash"] = None
        if body.freeze_paths is not None:
            updates["freeze_paths"] = body.freeze_paths
        if body.mutate_paths is not None:
            updates["mutate_paths"] = body.mutate_paths
        if body.role is not None:
            updates["role"] = body.role
        if body.external_handoff is not None:
            updates["external_handoff"] = body.external_handoff
        updated = step.model_copy(update=updates)
        prog = _replace_step(prog, updated)
        saved = ctx.programs.put(prog)
        return {"program": saved.model_dump(mode="json")}

    @app.post("/v1/programs/{program_id}/steps/{step_id}/preview")
    def preview_step(
        program_id: str,
        step_id: str,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _get_program(program_id, tenant_id)
        step = _find_step(prog, step_id)
        try:
            goal = materialize_step_goal(prog, step)
        except MaterializeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        warnings = stress_step(prog, step, goal=goal)
        ph = preview_hash(goal)
        updated = step.model_copy(update={"criteria_preview_hash": ph})
        prog = _replace_step(prog, updated)
        ctx.programs.put(prog)
        criteria = [c.model_dump(mode="json") for c in compile_goal(goal)]
        blocked = any(w.severity == "block" for w in warnings)
        return {
            "goal": goal.model_dump(mode="json"),
            "criteria": criteria,
            "criteria_preview_hash": ph,
            "budget": resolve_run_budget(goal).model_dump(mode="json"),
            "warnings": [w.to_dict() for w in warnings],
            "blocked": blocked,
            "freeze_enforcement": prog.freeze_enforcement,
        }

    @app.post("/v1/programs/{program_id}/steps/{step_id}/run")
    def run_step(
        program_id: str,
        step_id: str,
        body: StepRunBody,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        """GP0: plan_only preview envelope, or bind an existing run_id after POST /v1/runs."""

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _refresh_step_statuses(_get_program(program_id, tenant_id))
        step = _find_step(prog, step_id)

        if body.idempotency_key:
            idem_key = f"{tenant_id}:{program_id}:{step_id}:{body.idempotency_key}"
            prior = ctx._program_idempotency.get(idem_key)
            if prior and step.current_run_id == prior:
                return {
                    "program": prog.model_dump(mode="json"),
                    "step_id": step_id,
                    "run_id": prior,
                    "idempotent": True,
                }

        try:
            goal = materialize_step_goal(prog, step)
            assert_gp0_execution_prereqs(
                prog, step, workdir=body.workdir, plan_only=body.plan_only
            )
        except MaterializeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        warnings = stress_step(prog, step, goal=goal)
        if any(w.severity == "block" for w in warnings):
            raise HTTPException(
                status_code=400,
                detail={"message": "blocked by stress", "warnings": [w.to_dict() for w in warnings]},
            )

        budget = resolve_run_budget(goal, body.budget)
        if prog.budget and prog.budget.max_cost_usd is not None:
            remaining = prog.budget.max_cost_usd - prog.budget.spent_cost_usd
            step_cap = budget.max_cost_usd
            need = float(step_cap) if step_cap is not None else 0.0
            if remaining <= 0 or (step_cap is not None and need > remaining):
                raise HTTPException(status_code=429, detail="program budget exhausted")
        ph = preview_hash(goal)
        # Persist preview hash whenever we materialize for run/envelope
        step = step.model_copy(update={"criteria_preview_hash": ph})
        prog = _replace_step(prog, step)
        ctx.programs.put(prog)

        if body.plan_only or body.bind_run_id is None:
            # Envelope for human confirm → POST /v1/runs → bind
            return {
                "plan_only": body.plan_only or body.bind_run_id is None,
                "run_create": {
                    "goal": goal.model_dump(mode="json"),
                    "task_class": goal.task_class or prog.task_class,
                    "budget": budget.model_dump(mode="json"),
                    "workdir": body.workdir,
                },
                "criteria_preview_hash": ph,
                "warnings": [w.to_dict() for w in warnings],
                "blocked": False,
                "ready": step_is_ready(prog, step),
                "hint": "POST /v1/runs with run_create, then POST this endpoint with bind_run_id",
            }

        if prog.status != "active":
            raise HTTPException(status_code=409, detail="program is not active")
        if not step_is_ready(prog, step) and step.status not in {"failed", "ready", "planned"}:
            raise HTTPException(status_code=409, detail="step is not runnable")
        prev = previous_step(prog, step)
        if prev is not None and prev.status not in {"succeeded", "skipped"}:
            raise HTTPException(
                status_code=409,
                detail=f"previous step {prev.step_id} not succeeded",
            )

        run_id = body.bind_run_id
        rec = ctx.runs.get((tenant_id, run_id))
        if rec is None:
            raise HTTPException(status_code=404, detail="run not found for tenant")

        # Bind integrity: preview hash must be current; run criteria_hash must match when set.
        if not step.criteria_preview_hash:
            raise HTTPException(
                status_code=400,
                detail="preview step before bind (missing criteria_preview_hash)",
            )
        if ph != step.criteria_preview_hash:
            raise HTTPException(
                status_code=409,
                detail="goal changed since preview; re-run preview before bind",
            )
        run_hash = rec.criteria_hash
        if run_hash is None:
            loaded = ctx.load_from_checkpoints(ctx.root, tenant_id, run_id)
            if loaded is not None:
                run_hash = loaded.criteria_hash
                if loaded.criteria_hash and (tenant_id, run_id) in ctx.runs:
                    ctx.runs[(tenant_id, run_id)] = rec.model_copy(
                        update={"criteria_hash": loaded.criteria_hash}
                    )
        if run_hash is not None and run_hash != step.criteria_preview_hash:
            raise HTTPException(
                status_code=409,
                detail=(
                    "bound run criteria_hash does not match step criteria_preview_hash; "
                    "submit the materialized Goal from preview"
                ),
            )
        if run_hash is None and (
            rec.terminal in step.acceptance_gate.terminal_in
            or rec.status in step.acceptance_gate.terminal_in
        ):
            # Terminal success without a hash cannot prove lock integrity.
            raise HTTPException(
                status_code=409,
                detail="terminal run missing criteria_hash; cannot verify bind integrity",
            )

        # Idempotent rebinding of same run
        if step.current_run_id == run_id:
            return {
                "program": prog.model_dump(mode="json"),
                "step_id": step_id,
                "run_id": run_id,
                "idempotent": True,
            }
        if step.status in {"queued", "running"} and step.current_run_id:
            raise HTTPException(status_code=409, detail="step already has an in-flight run")

        run_ids = list(step.run_ids)
        if run_id not in run_ids:
            run_ids.append(run_id)

        terminal = rec.terminal or rec.status
        gate = step.acceptance_gate.terminal_in
        if terminal in gate:
            new_status = "succeeded"
        elif terminal in {"queued", "running", None} or rec.status in {"queued", "running"}:
            new_status = "running" if rec.status == "running" else "queued"
        else:
            new_status = "failed"

        updated = step.model_copy(
            update={
                "run_ids": run_ids,
                "current_run_id": run_id,
                "status": new_status,
                "criteria_preview_hash": ph,
            }
        )
        prog = _replace_step(prog, updated)
        if new_status == "failed":
            prog = prog.model_copy(update={"status": "blocked"})
        elif new_status == "succeeded":
            # complete if all done
            if all(s.status in {"succeeded", "skipped"} for s in prog.steps):
                prog = prog.model_copy(update={"status": "completed"})
            else:
                prog = prog.model_copy(update={"status": "active"})
            prog = _refresh_step_statuses(prog)

        saved = ctx.programs.put(prog)
        if body.idempotency_key:
            ctx._program_idempotency[
                f"{tenant_id}:{program_id}:{step_id}:{body.idempotency_key}"
            ] = run_id
        return {
            "program": saved.model_dump(mode="json"),
            "step_id": step_id,
            "run_id": run_id,
            "step_status": new_status,
            "idempotent": False,
        }

    @app.post("/v1/programs/{program_id}/steps/{step_id}/skip")
    def skip_step(
        program_id: str,
        step_id: str,
        body: StepSkipBody,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        if not (body.note or "").strip():
            raise HTTPException(status_code=400, detail="skip requires a non-empty note")
        prog = _get_program(program_id, tenant_id)
        if prog.status not in {"active", "blocked"}:
            raise HTTPException(status_code=409, detail="program not active")
        step = _find_step(prog, step_id)
        if step.status in {"succeeded", "queued", "running"}:
            raise HTTPException(status_code=409, detail="cannot skip step in current status")
        updated = step.model_copy(
            update={"status": "skipped", "skip_note": body.note.strip()}
        )
        prog = _replace_step(prog, updated)
        if all(s.status in {"succeeded", "skipped"} for s in prog.steps):
            prog = prog.model_copy(update={"status": "completed"})
        else:
            prog = prog.model_copy(update={"status": "active"})
        prog = _refresh_step_statuses(prog)
        saved = ctx.programs.put(prog)
        return {"program": saved.model_dump(mode="json"), "step_id": step_id, "skipped": True}

    @app.post("/v1/programs/{program_id}/repo-binding")
    def set_repo_binding(
        program_id: str,
        body: RepoBindingBody,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        from recertia.programs.git_tip import GitTipError, resolve_binding_root

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _get_program(program_id, tenant_id)
        binding = RepoBinding(
            binding_id=body.binding_id,
            root=body.root,
            default_branch=body.default_branch,
            remote_url=body.remote_url,
        )
        try:
            root = resolve_binding_root(ctx.root, tenant_id, binding)
        except GitTipError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        prog = prog.model_copy(update={"repo_binding": binding, "handoff": "git_tip"})
        saved = ctx.programs.put(prog)
        return {
            "program": saved.model_dump(mode="json"),
            "resolved_root": str(root),
        }

    @app.post("/v1/programs/{program_id}/steps/{step_id}/record-tip")
    def record_step_tip(
        program_id: str,
        step_id: str,
        body: RecordTipBody,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        from recertia.programs.git_tip import (
            GitTipError,
            record_tip,
            resolve_binding_root,
        )

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _get_program(program_id, tenant_id)
        step = _find_step(prog, step_id)
        if step.status not in {"succeeded", "running", "queued", "ready", "planned"}:
            raise HTTPException(status_code=409, detail="step cannot record tip in this status")
        try:
            if body.use_binding_root:
                if prog.repo_binding is None:
                    raise GitTipError("no repo_binding registered")
                repo = resolve_binding_root(ctx.root, tenant_id, prog.repo_binding)
            else:
                rel = (body.workdir or "").strip().lstrip("/")
                if not rel or ".." in Path(rel).parts:
                    raise GitTipError("workdir required (relative under tenant workspaces)")
                repo = (ctx.root / "workspaces" / tenant_id / rel).resolve()
                try:
                    repo.relative_to((ctx.root / "workspaces" / tenant_id).resolve())
                except ValueError as exc:
                    raise GitTipError("workdir escapes tenant workspaces") from exc
            sha = record_tip(repo)
        except GitTipError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        eh = step.external_handoff or ExternalHandoff()
        eh = eh.model_copy(update={"head_sha": sha})
        updated = step.model_copy(update={"external_handoff": eh})
        prog = _replace_step(prog, updated)
        saved = ctx.programs.put(prog)
        return {"program": saved.model_dump(mode="json"), "head_sha": sha}

    @app.post("/v1/programs/{program_id}/steps/{step_id}/seed-workdir")
    def seed_step_workdir(
        program_id: str,
        step_id: str,
        body: SeedWorkdirBody,
        request: Request,
        principal=Depends(require_runs),
        x_recertia_tenant: str | None = Header(default=None, alias="X-Recertia-Tenant"),
    ) -> dict[str, Any]:
        """Checkout predecessor tip into a fresh canonical run workdir (no shared mount)."""

        from recertia.programs.git_tip import (
            GitTipError,
            checkout_tip,
            resolve_binding_root,
            resolve_tip_sha,
        )

        tenant_id = _resolve_tenant(principal, request, x_recertia_tenant)
        prog = _get_program(program_id, tenant_id)
        step = _find_step(prog, step_id)
        try:
            if prog.handoff != "git_tip":
                raise GitTipError("program handoff is not git_tip")
            if prog.repo_binding is None:
                raise GitTipError("unregistered repo cannot use git_tip")
            tip = resolve_tip_sha(
                prog, step, api_root=ctx.root, explicit=body.tip_sha
            )
            binding_root = resolve_binding_root(ctx.root, tenant_id, prog.repo_binding)
            dest = ctx.canonical_run_workdir(ctx.root, tenant_id, body.run_id)
            checked = checkout_tip(binding_root=binding_root, tip_sha=tip, dest=dest)
        except GitTipError as exc:
            # Mark step failed / program blocked on checkout failure
            failed = step.model_copy(update={"status": "failed"})
            prog = _replace_step(prog, failed).model_copy(update={"status": "blocked"})
            ctx.programs.put(prog)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "run_id": body.run_id,
            "tip_sha": tip,
            "checked_out": checked,
            "workdir": str(dest),
            "program_id": program_id,
            "step_id": step_id,
        }

    # Expose async create helper used by patched POST /v1/runs
    app.state.console_ctx = ctx
