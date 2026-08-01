#!/usr/bin/env python3
"""Smoke-test the OCI container execution backend end-to-end.

Usage:
  python3 scripts/smoke_container.py
  FANDEA_CONTAINER_RUNTIME=podman python3 scripts/smoke_container.py

Exits 0 on solved, 2 if no runtime, 1 on failure.
Requires Docker or Podman and a pulled allowlisted image (default python:3.12-slim).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from fandea.bootstrap import build_default_orchestrator  # noqa: E402
from fandea.solver.container import (  # noqa: E402
    container_runtime,
    ensure_execution_ready,
    ensure_workdir_writable_by_container,
    probe_container_runtime,
)
from fandea.solver.sandbox import SandboxError  # noqa: E402


def main() -> int:
    os.environ["FANDEA_EXECUTION_BACKEND"] = "container"
    # Do not inherit test-suite local default.
    os.environ.pop("FANDEA_FORCE_LOCAL", None)

    runtime = container_runtime()
    if runtime is None:
        print("FAIL: no Docker/Podman on PATH", file=sys.stderr)
        return 2

    try:
        ensure_execution_ready()
        probe_container_runtime()
    except SandboxError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    from datetime import datetime, timezone

    from contracts.budget import Budget
    from contracts.criteria import SensitivityProof, TaskCriterion
    from contracts.goal import DesiredState, Goal
    from contracts.run import Task

    with tempfile.TemporaryDirectory(prefix="fandea-smoke-") as tmp:
        root = Path(tmp)
        workdir = root / "work"
        workdir.mkdir()
        ensure_workdir_writable_by_container(workdir)

        run_id = f"smoke-{uuid.uuid4().hex[:8]}"
        goal = Goal(
            desired=[DesiredState(id="marker", kind="file_exists", path="SMOKE_OK")],
            context="create SMOKE_OK marker via container sandbox",
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
                    negative_fixture="empty workspace",
                    rejected=True,
                    checked_at=datetime.now(timezone.utc),
                ),
            )
        ]
        script = ["python3 -c \"open('SMOKE_OK','w').write('ok')\""]

        bundle = build_default_orchestrator(
            root / "runs",
            skills_root=root / "skills",
            facts_root=root / "facts",
        )
        try:
            state = bundle.orchestrator.start(
                run_id,
                task,
                criteria,
                budget=Budget(max_attempts=2),
                workdir=workdir,
                script=script,
                arm="treatment",
            )
        finally:
            bundle.close()

        marker = workdir / "SMOKE_OK"
        summary = {
            "runtime": runtime,
            "terminal": state.terminal,
            "marker_exists": marker.exists(),
            "marker_text": marker.read_text() if marker.exists() else None,
            "route_tail": [
                {"node": e.node, "route": e.route, "reason": e.reason}
                for e in state.route_log[-6:]
            ],
        }
        print(json.dumps(summary, indent=2))
        if state.terminal == "solved" and marker.exists():
            print("PASS: container smoke solved and wrote SMOKE_OK")
            return 0
        print("FAIL: expected terminal=solved with SMOKE_OK", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
