"""GP0 migration programs (Goal packs) conformance."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from contracts.budget import Budget
from contracts.goal import Constraint, DesiredState, Goal, compile_goal
from contracts.program import MigrationProgram, MigrationStep, budget_from_goal_constraints
from recertia.api import RunRecord, create_app
from recertia.nodes._util import criteria_hash
from recertia.programs.materialize import (
    MaterializeError,
    assert_freeze_enforcement_allowed,
    assert_gp0_execution_prereqs,
    materialize_step_goal,
    preview_hash,
)
from recertia.programs.stress import stress_step


def _step(
    step_id: str,
    ordinal: int,
    *,
    role: str = "custom",
    path: str = "README.md",
    freeze: list[str] | None = None,
    mutate: list[str] | None = None,
) -> dict:
    return {
        "step_id": step_id,
        "ordinal": ordinal,
        "title": step_id,
        "role": role,
        "goal": {
            "desired": [
                {"id": f"{step_id}-d", "kind": "file_exists", "path": path, "weight": 1.0}
            ],
            "context": f"context for {step_id}",
            "task_class": "repo-chore",
        },
        "freeze_paths": freeze or [],
        "mutate_paths": mutate or [],
    }


def _client(tmp_path: Path) -> tuple[TestClient, Any]:
    app = create_app(root=tmp_path / "api-root", skills_root=tmp_path / "skills")
    return TestClient(app), app


def _issue(app: Any, *, tenant_id: str = "t1") -> dict[str, str]:
    issued = app.state.api_keys.issue(
        tenant_id=tenant_id,
        scopes={"runs", "metrics", "exec", "admin"},
        actor="test",
    )
    return {"X-API-Key": issued.secret}


def test_budget_ceiling_applied_to_run_budget() -> None:
    goal = Goal(
        desired=[DesiredState(id="f", kind="file_exists", path="x")],
        constraints=[Constraint(id="cost", kind="budget_ceiling", value=2.5)],
    )
    b = budget_from_goal_constraints(goal, Budget(max_cost_usd=10.0))
    assert b.max_cost_usd == 2.5


def test_materialize_advisory_freeze_does_not_inject_must_not_modify() -> None:
    step = MigrationStep.model_validate(_step("s1", 0, freeze=["src/api"]))
    prog = MigrationProgram(
        program_id="p1",
        tenant_id="t1",
        title="t",
        freeze_enforcement="advisory",
        steps=[step],
    )
    goal = materialize_step_goal(prog, step)
    assert not any(c.kind == "must_not_modify" for c in goal.constraints)
    warnings = stress_step(prog, step, goal=goal)
    assert any(w.code == "freeze_advisory" for w in warnings)


def test_materialize_hard_freeze_injects_constraint() -> None:
    step = MigrationStep.model_validate(_step("s1", 0, freeze=["src/api"]))
    prog = MigrationProgram(
        program_id="p1",
        tenant_id="t1",
        title="t",
        freeze_enforcement="hard",
        steps=[step],
    )
    goal = materialize_step_goal(prog, step)
    assert any(c.kind == "must_not_modify" for c in goal.constraints)


def test_freeze_mutate_overlap_blocks() -> None:
    step = MigrationStep.model_validate(
        _step("s1", 0, freeze=["src/api"], mutate=["src/api"])
    )
    prog = MigrationProgram(
        program_id="p1", tenant_id="t1", title="t", steps=[step]
    )
    with pytest.raises(MaterializeError, match="freeze_mutate_overlap"):
        materialize_step_goal(prog, step)


def test_program_bar_merge() -> None:
    step = MigrationStep.model_validate(_step("s2", 1, role="structural"))
    prog = MigrationProgram(
        program_id="p1",
        tenant_id="t1",
        title="t",
        steps=[step],
        program_bar_desired=[
            DesiredState(id="bar", kind="command", run="python -m pytest -q", weight=1.0)
        ],
    )
    goal = materialize_step_goal(prog, step)
    assert any(d.id == "bar" for d in goal.desired)


def test_gp0_execution_prereqs() -> None:
    step = MigrationStep.model_validate(_step("s1", 0))
    prog = MigrationProgram(
        program_id="p1", tenant_id="t1", title="t", handoff="none", steps=[step]
    )
    with pytest.raises(MaterializeError, match="workdir"):
        assert_gp0_execution_prereqs(prog, step, workdir=None, plan_only=False)
    assert_gp0_execution_prereqs(prog, step, workdir=None, plan_only=True)


def test_gp_t1_accept_creates_zero_runs(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app)
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={
            "title": "provider port",
            "intent": "extract provider",
            "steps": [
                _step("char", 0, role="characterization"),
                _step("move", 1, role="structural", path="src"),
            ],
        },
    )
    assert created.status_code == 200, created.text
    pid = created.json()["program"]["program_id"]
    accepted = client.post(
        f"/v1/programs/{pid}/accept",
        headers=headers,
        json={"ack_disclaimer": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["program"]["status"] == "active"
    assert app.state.runs == {}


def test_gp_t5_tenant_isolation(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    ha = _issue(app, tenant_id="tenant-a")
    hb = _issue(app, tenant_id="tenant-b")
    created = client.post(
        "/v1/programs",
        headers=ha,
        json={"title": "a", "steps": [_step("s1", 0)]},
    )
    pid = created.json()["program"]["program_id"]
    denied = client.get(f"/v1/programs/{pid}", headers=hb)
    assert denied.status_code == 404


def test_hard_freeze_allowed_after_sealing() -> None:
    assert_freeze_enforcement_allowed("hard")
    assert_freeze_enforcement_allowed("advisory")


def test_create_allows_hard_freeze(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app)
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={
            "title": "x",
            "freeze_enforcement": "hard",
            "steps": [_step("s1", 0, freeze=["README.md"])],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["program"]["freeze_enforcement"] == "hard"


def _bind_solved_run(
    client: TestClient,
    app: Any,
    headers: dict[str, str],
    *,
    tenant_id: str,
    program_id: str,
    step_id: str,
    run_id: str,
    idempotency_key: str | None = None,
) -> Any:
    prev = client.post(f"/v1/programs/{program_id}/steps/{step_id}/preview", headers=headers)
    assert prev.status_code == 200, prev.text
    ph = prev.json()["criteria_preview_hash"]
    goal = Goal.model_validate(prev.json()["goal"])
    # Match intake hash algorithm used for bind integrity
    ch = criteria_hash(compile_goal(goal))
    assert ch == ph
    app.state.runs[(tenant_id, run_id)] = RunRecord(
        run_id=run_id,
        request="x",
        task_class="repo-chore",
        status="solved",
        created_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
        terminal="solved",
        has_goal=True,
        criteria_hash=ph,
    )
    body: dict[str, Any] = {"bind_run_id": run_id, "workdir": "ws"}
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    return client.post(
        f"/v1/programs/{program_id}/steps/{step_id}/run",
        headers=headers,
        json=body,
    )


def test_gp_t3_bind_run_and_linear_gate(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app, tenant_id="t1")
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={
            "title": "mig",
            "steps": [
                _step("char", 0, role="characterization"),
                _step("move", 1, role="structural"),
            ],
        },
    )
    pid = created.json()["program"]["program_id"]
    client.post(f"/v1/programs/{pid}/accept", headers=headers, json={"ack_disclaimer": True})

    # Second step cannot bind before first succeeds
    app.state.runs[("t1", "run-early")] = RunRecord(
        run_id="run-early",
        request="x",
        task_class="repo-chore",
        status="solved",
        created_at=datetime.now(timezone.utc),
        tenant_id="t1",
        terminal="solved",
        has_goal=True,
        criteria_hash="deadbeef",
    )
    client.post(f"/v1/programs/{pid}/steps/move/preview", headers=headers)
    blocked = client.post(
        f"/v1/programs/{pid}/steps/move/run",
        headers=headers,
        json={"bind_run_id": "run-early", "workdir": "ws"},
    )
    assert blocked.status_code == 409

    bound = _bind_solved_run(
        client,
        app,
        headers,
        tenant_id="t1",
        program_id=pid,
        step_id="char",
        run_id="run-char",
        idempotency_key="k1",
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["step_status"] == "succeeded"
    again = client.post(
        f"/v1/programs/{pid}/steps/char/run",
        headers=headers,
        json={"bind_run_id": "run-char", "workdir": "ws", "idempotency_key": "k1"},
    )
    assert again.json()["idempotent"] is True

    move = _bind_solved_run(
        client,
        app,
        headers,
        tenant_id="t1",
        program_id=pid,
        step_id="move",
        run_id="run-move",
    )
    assert move.status_code == 200
    assert move.json()["program"]["status"] == "completed"


def test_bind_rejects_mismatched_criteria_hash(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app, tenant_id="t1")
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={"title": "p", "steps": [_step("s1", 0)]},
    )
    pid = created.json()["program"]["program_id"]
    client.post(f"/v1/programs/{pid}/accept", headers=headers, json={"ack_disclaimer": True})
    client.post(f"/v1/programs/{pid}/steps/s1/preview", headers=headers)
    app.state.runs[("t1", "run-bad")] = RunRecord(
        run_id="run-bad",
        request="x",
        task_class="repo-chore",
        status="solved",
        created_at=datetime.now(timezone.utc),
        tenant_id="t1",
        terminal="solved",
        has_goal=True,
        criteria_hash="not-the-preview-hash",
    )
    bad = client.post(
        f"/v1/programs/{pid}/steps/s1/run",
        headers=headers,
        json={"bind_run_id": "run-bad", "workdir": "ws"},
    )
    assert bad.status_code == 409


def test_preview_does_not_lock(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app)
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={"title": "p", "steps": [_step("s1", 0)]},
    )
    pid = created.json()["program"]["program_id"]
    prev = client.post(f"/v1/programs/{pid}/steps/s1/preview", headers=headers)
    assert prev.status_code == 200
    assert prev.json()["criteria_preview_hash"]
    assert preview_hash(
        Goal.model_validate(prev.json()["goal"])
    ) == prev.json()["criteria_preview_hash"]
    assert app.state.runs == {}


def test_plan_only_envelope(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app)
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={"title": "p", "steps": [_step("s1", 0)]},
    )
    pid = created.json()["program"]["program_id"]
    client.post(f"/v1/programs/{pid}/accept", headers=headers, json={"ack_disclaimer": True})
    env = client.post(
        f"/v1/programs/{pid}/steps/s1/run",
        headers=headers,
        json={"plan_only": True},
    )
    assert env.status_code == 200
    assert "run_create" in env.json()
    assert app.state.runs == {}


def test_suggest_decompositions_and_from_pack(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app)
    sug = client.post(
        "/v1/goals/suggest",
        headers=headers,
        json={
            "context": (
                "Please re-architect the monolith toward hexagonal boundaries and "
                "split the repository interface with backward-compatible adapters. "
                "This is a long migration brief that should prefer a Goal pack."
            ),
            "use_model": False,
        },
    )
    assert sug.status_code == 200, sug.text
    body = sug.json()
    assert body.get("pack")
    assert body.get("decompositions")
    created = client.post(
        "/v1/programs/from-pack",
        headers=headers,
        json={
            "title": "From suggest",
            "intent": body["context"],
            "decomposition": body["decompositions"][0]["decomposition"],
            "steps": body["decompositions"][0]["steps"],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["program"]["status"] == "draft"
    assert len(created.json()["program"]["steps"]) >= 2


def test_goals_probe_read_only(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app, tenant_id="t1")
    root = tmp_path / "api-root" / "workspaces" / "t1" / "ws"
    root.mkdir(parents=True)
    (root / "README.md").write_text("hi", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    probed = client.post(
        "/v1/goals/probe",
        headers=headers,
        json={"workdir": "ws"},
    )
    assert probed.status_code == 200, probed.text
    assert probed.json()["locked"] is False
    assert probed.json()["probe"]["exists"] is True


def test_skip_step(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    headers = _issue(app)
    created = client.post(
        "/v1/programs",
        headers=headers,
        json={
            "title": "skip-me",
            "steps": [_step("a", 0), _step("b", 1)],
        },
    )
    pid = created.json()["program"]["program_id"]
    client.post(f"/v1/programs/{pid}/accept", headers=headers, json={"ack_disclaimer": True})
    skipped = client.post(
        f"/v1/programs/{pid}/steps/a/skip",
        headers=headers,
        json={"note": "already characterized offline"},
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["program"]["steps"][0]["status"] == "skipped"
