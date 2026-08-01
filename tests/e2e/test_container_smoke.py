"""OCI container backend smoke tests (plan items 5–8).

Skipped when Docker/Podman is missing or the runtime cannot run a probe container
(common in restricted VMs). CI's ``container-smoke`` job requires a working daemon.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.budget import Budget
from contracts.criteria import SensitivityProof, TaskCriterion
from contracts.goal import DesiredState, Goal
from contracts.run import Task
from recertia.bootstrap import build_default_orchestrator
from recertia.solver.container import (
    container_runtime,
    ensure_execution_ready,
    ensure_workdir_writable_by_container,
    probe_container_runtime,
)
from recertia.solver.sandbox import SandboxError


def _require_working_container(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("RECERTIA_EXECUTION_BACKEND", "container")
    runtime = container_runtime()
    if runtime is None:
        pytest.skip("Docker/Podman not on PATH")
    try:
        ensure_execution_ready()
        probe_container_runtime(timeout_s=90)
    except SandboxError as exc:
        pytest.skip(f"container runtime not usable: {exc}")
    return runtime


def test_default_container_image_accepts_digest_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    from recertia.solver.container import default_container_image

    monkeypatch.setenv(
        "RECERTIA_CONTAINER_IMAGE",
        "python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
    )
    assert default_container_image().startswith("python:3.12-slim@sha256:")


def test_container_workdir_chmod_defaults_without_world_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RECERTIA_WORKDIR_WORLD_WRITE", raising=False)
    work = tmp_path / "w"
    work.mkdir(mode=0o755)
    ensure_workdir_writable_by_container(work)
    mode = work.stat().st_mode & 0o777
    assert mode & 0o070 == 0o070  # group write
    assert mode & 0o002 == 0  # other-write off by default


def test_container_workdir_chmod_world_write_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECERTIA_WORKDIR_WORLD_WRITE", "1")
    work = tmp_path / "w"
    work.mkdir(mode=0o755)
    ensure_workdir_writable_by_container(work)
    assert work.stat().st_mode & 0o0007 == 0o0007


def test_container_smoke_solves_goal_via_oci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_working_container(monkeypatch)

    workdir = tmp_path / "work"
    workdir.mkdir()
    run_id = "container-smoke-1"
    goal = Goal(
        desired=[DesiredState(id="marker", kind="file_exists", path="SMOKE_OK")],
        context="write SMOKE_OK in the OCI sandbox",
        task_class="repo-chore",
    )
    task = Task(
        task_id=run_id,
        goal=goal,
        request=goal.context,
        task_class="repo-chore",
        submitted_at=datetime.now(timezone.utc),
    )
    criteria = [
        TaskCriterion(
            id="marker",
            kind="command",
            run="test -f SMOKE_OK",
            source="caller",
            weight=1.0,
            sensitivity_proof=SensitivityProof(
                criterion_id="marker",
                negative_fixture="empty",
                rejected=True,
                checked_at=datetime.now(timezone.utc),
            ),
        )
    ]
    bundle = build_default_orchestrator(
        tmp_path / "runs",
        skills_root=tmp_path / "skills",
        facts_root=tmp_path / "facts",
    )
    try:
        state = bundle.orchestrator.start(
            run_id,
            task,
            criteria,
            budget=Budget(max_attempts=2),
            workdir=workdir,
            script=["python3 -c \"open('SMOKE_OK','w').write('ok')\""],
        )
    finally:
        bundle.close()

    assert state.terminal == "solved"
    assert (workdir / "SMOKE_OK").read_text() == "ok"
    # Ensure we did not silently flip to local.
    assert os.environ.get("RECERTIA_EXECUTION_BACKEND") == "container"
