"""Minimal golden-regression runner (M1; specs §8 regression gate, refactor-plan B6).

One golden task per seed skill, run before that skill's ``SkillStatus.lifecycle`` is set to
``approved``. The full harness (fixtures per task class, snapshot pinning, ``causal_lift``)
is M4; this is the narrow slice the seed library needs so "approving the seed library" is
not a documented exception to a rule that does not exist yet.

A golden task is a directory::

    evals/golden/<task_class>/<skill_id>/
        task.json          # {request, expected_skill_id, expected_version?, criteria?}
        workspace/         # fixture files copied into the run workdir
        expect.json        # {terminal: "solved"} (M1 minimal)

The runner applies the skill's shell steps against the fixture and scores the task criteria
(or the skill's non-judge certification criteria when the task supplies none). The log is
the evidence of the regression gate — not a note in a PR description.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from contracts.budget import Budget
from contracts.criteria import SensitivityProof, TaskCriterion
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
    return path if path.is_dir() and (path / "task.json").exists() else None


def run_golden_for_skill(
    version: SkillVersion,
    golden_dir: Path,
    *,
    runs_root: Path,
    use_skill_script: bool = True,
) -> GoldenResult:
    """Execute one golden task against ``version``; return a :class:`GoldenResult`."""

    task_spec = json.loads((golden_dir / "task.json").read_text(encoding="utf-8"))
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
    workdir.mkdir(parents=True, exist_ok=True)
    fixture = golden_dir / "workspace"
    if fixture.exists():
        for item in fixture.iterdir():
            dest = workdir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    criteria = _criteria_from_task(task_spec, version)
    script = script_from_skill(version) if use_skill_script else task_spec.get("script", ["true"])

    run_id = f"golden-{version.skill_id}-v{version.version}-{uuid.uuid4().hex[:6]}"
    orch = GraphOrchestrator(runs_root / "golden-runs")
    try:
        state = orch.start(
            run_id,
            Task(
                task_id=run_id,
                request=task_spec["request"],
                task_class=version.task_class,
                submitted_at=datetime.now(timezone.utc),
                is_eval_fixture=True,
            ),
            criteria,
            budget=Budget(max_attempts=2),
            workdir=workdir,
            script=script,
        )
    finally:
        orch.close()

    passed = state.terminal == expected_terminal
    return GoldenResult(
        skill_id=version.skill_id,
        version=version.version,
        golden_path=str(golden_dir),
        passed=passed,
        terminal=state.terminal,
        run_id=run_id,
        detail=f"expected terminal={expected_terminal!r}, got {state.terminal!r}",
    )


def run_task_class_gate(
    version: SkillVersion,
    golden_root: Path,
    *,
    runs_root: Path,
    task_class: str | None = None,
) -> GoldenReport:
    """Run every golden under ``golden_root/<task_class>/`` against ``version`` (M3 harness).

    This is the same runner ``run_golden_for_skill`` uses — review approval and seed promotion
    share one mechanism (specs §8).
    """

    task_class = task_class or version.task_class
    report = GoldenReport()
    class_root = golden_root / task_class
    if not class_root.is_dir():
        return report
    for child in sorted(p for p in class_root.iterdir() if p.is_dir() and (p / "task.json").exists()):
        # Skip private/helper dirs.
        if child.name.startswith("_"):
            continue
        report.results.append(
            run_golden_for_skill(version, child, runs_root=runs_root, use_skill_script=True)
        )
    return report


def run_seed_library_gate(
    store: SkillStore,
    golden_root: Path,
    *,
    runs_root: Path,
    log_path: Path,
    skill_ids: list[str] | None = None,
) -> GoldenReport:
    """Run the golden task for every (or selected) skill; write the regression log."""

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
        return [TaskCriterion(**c) for c in task_spec["criteria"]]
    # Fall back to the skill's required non-judge certification criteria, adapted as TaskCriterion.
    out: list[TaskCriterion] = []
    for c in version.certification_criteria:
        if c.kind == "judge" or not c.is_required:
            continue
        proof = c.sensitivity_proof or SensitivityProof(
            criterion_id=c.id,
            negative_fixture="empty workspace",
            rejected=True,
            checked_at=datetime.now(timezone.utc),
        )
        out.append(
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
    if not out:
        out.append(
            TaskCriterion(
                id="default-ok",
                kind="command",
                run="true",
                source="caller",
                weight=1.0,
                sensitivity_proof=SensitivityProof(
                    criterion_id="default-ok",
                    negative_fixture="false",
                    rejected=True,
                    checked_at=datetime.now(timezone.utc),
                ),
            )
        )
    return out
