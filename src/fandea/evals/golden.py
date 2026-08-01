"""Minimal golden-regression runner (M1; specs §8 regression gate, refactor-plan B6).

One golden task per seed skill, run before that skill's ``SkillStatus.lifecycle`` is set to
``approved``. The full harness (fixtures per task class, snapshot pinning, ``causal_lift``)
is M4; this is the narrow slice the seed library needs so "approving the seed library" is
not a documented exception to a rule that does not exist yet.

A golden task is a directory::

    evals/golden/<task_class>/<skill_id>/
        goal.json          # preferred (Variant B Goal)
        task.json          # {request, expected_skill_id, expected_version?, criteria?}
        workspace/         # fixture files copied into the run workdir
        expect.json        # {terminal: "solved"} (M1 minimal)

When ``goal.json`` is present it is used as the primary input; ``task.json`` request remains
the legacy fallback.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from contracts.budget import Budget
from contracts.criteria import TaskCriterion
from contracts.goal import Goal, compile_goal
from contracts.run import Task
from contracts.skill import SkillVersion
from fandea.graph.engine import GraphOrchestrator
from fandea.memory.procedural.apply import script_from_skill
from fandea.memory.procedural.store import SkillStore


@dataclass
class GoldenResult:
    skill_id: str
    version: int
    golden_path: str
    passed: bool
    terminal: str | None
    run_id: str
    detail: str = ""
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GoldenReport:
    results: list[GoldenResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "all_passed": self.all_passed,
            "results": [
                {
                    "skill_id": r.skill_id,
                    "version": r.version,
                    "golden_path": r.golden_path,
                    "passed": r.passed,
                    "terminal": r.terminal,
                    "run_id": r.run_id,
                    "detail": r.detail,
                    "at": r.at.isoformat(),
                }
                for r in self.results
            ],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def discover_golden(golden_root: Path, skill_id: str, task_class: str = "repo-chore") -> Path | None:
    path = golden_root / task_class / skill_id
    has_task = path.is_dir() and (path / "task.json").exists()
    has_goal = path.is_dir() and (path / "goal.json").exists()
    return path if has_task or has_goal else None


def run_golden_for_skill(
    version: SkillVersion,
    golden_dir: Path,
    *,
    runs_root: Path,
    use_skill_script: bool = True,
    snapshot_id: str | None = None,
    model_version: str | None = None,
) -> GoldenResult:
    """Execute one golden task against ``version``; return a :class:`GoldenResult`."""

    task_spec: dict = {}
    if (golden_dir / "task.json").exists():
        task_spec = json.loads((golden_dir / "task.json").read_text(encoding="utf-8"))

    goal: Goal | None = None
    if (golden_dir / "goal.json").exists():
        goal = Goal.model_validate_json((golden_dir / "goal.json").read_text(encoding="utf-8"))

    expect = {}
    expect_path = golden_dir / "expect.json"
    if expect_path.exists():
        expect = json.loads(expect_path.read_text(encoding="utf-8"))
    expected_terminal = expect.get("terminal", "solved")

    workdir = (
        runs_root
        / "golden-workspaces"
        / f"{version.skill_id}-v{version.version}-{uuid.uuid4().hex[:8]}"
    )
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    fixture = golden_dir / "workspace"
    if fixture.exists():
        for item in fixture.iterdir():
            dest = workdir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    try:
        if goal is not None and "criteria" not in task_spec:
            criteria = compile_goal(goal, source="caller")
        else:
            criteria = _criteria_from_task(task_spec, version)
    except ValueError as exc:
        return GoldenResult(
            skill_id=version.skill_id,
            version=version.version,
            golden_path=str(golden_dir),
            passed=False,
            terminal=None,
            run_id="",
            detail=str(exc),
        )
    script = script_from_skill(version) if use_skill_script else task_spec.get("script", ["true"])

    run_id = f"golden-{version.skill_id}-v{version.version}-{uuid.uuid4().hex[:6]}"
    from contracts.run import RunManifest

    pinned = RunManifest(
        model_version=model_version or "m4-harness",
        index_snapshot_id=snapshot_id,
        library_commit=snapshot_id,
    )
    request = task_spec.get("request") or (goal.context if goal else None)
    orch = GraphOrchestrator(runs_root / "golden-runs")
    previous_backend = os.environ.get("FANDEA_EXECUTION_BACKEND")
    if previous_backend is None:
        os.environ["FANDEA_EXECUTION_BACKEND"] = "local"
    try:
        state = orch.start(
            run_id,
            Task(
                task_id=run_id,
                goal=goal,
                request=request,
                task_class=version.task_class,
                submitted_at=datetime.now(timezone.utc),
                is_eval_fixture=True,
            ),
            criteria,
            budget=Budget(max_attempts=2),
            workdir=workdir,
            script=script,
            manifest=pinned,
            arm="treatment",
        )
    finally:
        orch.close()
        if previous_backend is None:
            os.environ.pop("FANDEA_EXECUTION_BACKEND", None)
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)

    passed = state.terminal == expected_terminal
    return GoldenResult(
        skill_id=version.skill_id,
        version=version.version,
        golden_path=str(golden_dir),
        passed=passed,
        terminal=state.terminal,
        run_id=run_id,
        detail=(
            f"expected terminal={expected_terminal!r}, got {state.terminal!r}; "
            f"snapshot={pinned.index_snapshot_id!r} model={pinned.model_version!r}"
        ),
    )


def run_task_class_gate(
    version: SkillVersion,
    golden_root: Path,
    *,
    runs_root: Path,
    task_class: str | None = None,
) -> GoldenReport:
    task_class = task_class or version.task_class
    report = GoldenReport()
    class_root = golden_root / task_class
    if not class_root.is_dir():
        return report
    for child in sorted(p for p in class_root.iterdir() if p.is_dir()):
        if child.name.startswith("_"):
            continue
        if not ((child / "task.json").exists() or (child / "goal.json").exists()):
            continue
        report.results.append(
            run_golden_for_skill(version, child, runs_root=runs_root, use_skill_script=True)
        )
    return report


def select_and_run_gate(
    version: SkillVersion,
    *,
    runs_root: Path,
    golden_root: Path | None = None,
    golden_dir: Path | None = None,
    require_task_class_gate: bool = False,
    require_fixture: bool = False,
) -> GoldenReport:
    prefer_task_class = require_task_class_gate or (
        require_fixture and golden_root is not None and golden_dir is None
    )
    if prefer_task_class:
        if golden_root is None:
            raise ValueError("task-class regression gate requires golden_root")
        report = run_task_class_gate(
            version, golden_root, runs_root=runs_root, task_class=version.task_class
        )
        if golden_dir is not None and golden_dir.is_dir():
            own = run_golden_for_skill(version, golden_dir, runs_root=runs_root)
            if not any(r.golden_path == own.golden_path for r in report.results):
                report.results.append(own)
        return report

    if golden_dir is not None:
        result = run_golden_for_skill(version, golden_dir, runs_root=runs_root)
        return GoldenReport(results=[result])

    if golden_root is not None:
        skill_dir = golden_root / version.task_class / version.skill_id
        if skill_dir.is_dir() and (
            (skill_dir / "task.json").exists() or (skill_dir / "goal.json").exists()
        ):
            return GoldenReport(
                results=[run_golden_for_skill(version, skill_dir, runs_root=runs_root)]
            )
        if (golden_root / version.task_class / ".full_class").exists():
            return run_task_class_gate(
                version,
                golden_root,
                runs_root=runs_root,
                task_class=version.task_class,
            )
        return GoldenReport()

    if require_fixture:
        raise ValueError("promote_to_approved requires golden_dir or golden_root")
    return GoldenReport()


def run_seed_library_gate(
    store: SkillStore,
    golden_root: Path,
    *,
    runs_root: Path,
    log_path: Path,
    skill_ids: list[str] | None = None,
) -> GoldenReport:
    report = GoldenReport()
    for version, _status, _stats in store.iter_loaded():
        if skill_ids is not None and version.skill_id not in skill_ids:
            continue
        golden = discover_golden(golden_root, version.skill_id, version.task_class)
        if golden is None:
            report.results.append(
                GoldenResult(
                    skill_id=version.skill_id,
                    version=version.version,
                    golden_path="",
                    passed=False,
                    terminal=None,
                    run_id="",
                    detail=f"no golden task under {golden_root}/{version.task_class}/{version.skill_id}",
                )
            )
            continue
        report.results.append(
            run_golden_for_skill(version, golden, runs_root=runs_root)
        )
    report.write(log_path)
    return report


def _criteria_from_task(task_spec: dict, version: SkillVersion) -> list[TaskCriterion]:
    if "criteria" in task_spec:
        out = [TaskCriterion(**c) for c in task_spec["criteria"]]
        proven = [
            c
            for c in out
            if c.is_required and c.kind != "judge" and c.is_preregistered_and_proven
        ]
        if not proven:
            raise ValueError(
                f"golden task cannot promote {version.skill_id}@v{version.version}: "
                "task criteria lack a required non-judge criterion with hashed rejecting "
                "sensitivity evidence"
            )
        return out
    adapted: list[TaskCriterion] = []
    for c in version.certification_criteria:
        if c.kind == "judge" or not c.is_required:
            continue
        if not c.is_preregistered_and_proven:
            raise ValueError(
                f"golden task cannot promote {version.skill_id}@v{version.version}: "
                f"criterion {c.id!r} lacks hashed rejecting sensitivity evidence"
            )
        proof = c.sensitivity_proof
        adapted.append(
            TaskCriterion(
                id=c.id,
                kind=c.kind,  # type: ignore[arg-type]
                run=c.run,
                expect_exit=c.expect_exit,
                source="task_class_template",
                weight=c.weight,
                sensitivity_proof=proof,
            )
        )
    if not adapted:
        raise ValueError(
            f"golden task cannot promote {version.skill_id}@v{version.version}: "
            "no required non-judge criterion with hashed sensitivity evidence"
        )
    if not any(c.is_preregistered_and_proven for c in adapted):
        raise ValueError(
            f"golden task cannot promote {version.skill_id}@v{version.version}: "
            "adapted task criteria failed sensitivity evidence verification"
        )
    return adapted
