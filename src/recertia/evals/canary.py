"""Judge false-pass canary (roadmap P1-2 / assumption a4).

Planted-failure fixtures must fail under a correct verifier. A pass is a false-pass
event attributed to the verifier model version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_CANARY_ROOT = Path("evals/canary/planted-failure")


@dataclass(frozen=True)
class CanaryCase:
    case_id: str
    workdir: Path
    command: str
    expect_pass: bool  # planted failures expect False


@dataclass(frozen=True)
class CanaryResult:
    case_id: str
    passed: bool
    false_pass: bool
    model_version: str | None


@dataclass(frozen=True)
class CanaryReport:
    model_version: str | None
    trials: int
    false_passes: int

    @property
    def false_pass_rate(self) -> float | None:
        if self.trials <= 0:
            return None
        return self.false_passes / self.trials


def load_planted_failure_cases(root: Path | str | None = None) -> list[CanaryCase]:
    base = Path(root) if root is not None else DEFAULT_CANARY_ROOT
    if not base.exists():
        return []
    cases: list[CanaryCase] = []
    for task_path in sorted(base.glob("*/task.json")):
        payload = json.loads(task_path.read_text(encoding="utf-8"))
        case_dir = task_path.parent
        workdir = case_dir / "workspace"
        cases.append(
            CanaryCase(
                case_id=payload.get("case_id") or case_dir.name,
                workdir=workdir,
                command=str(payload.get("command") or "test -f PASS"),
                expect_pass=bool(payload.get("expect_pass", False)),
            )
        )
    return cases


def score_canary_case(
    case: CanaryCase,
    *,
    runner: Callable[[str, Path], bool],
    model_version: str | None = None,
) -> CanaryResult:
    """``runner(command, workdir) -> passed`` is the verifier surface under test."""

    passed = bool(runner(case.command, case.workdir))
    false_pass = passed and not case.expect_pass
    return CanaryResult(
        case_id=case.case_id,
        passed=passed,
        false_pass=false_pass,
        model_version=model_version,
    )


def run_judge_canary(
    *,
    root: Path | str | None = None,
    runner: Callable[[str, Path], bool] | None = None,
    model_version: str | None = None,
) -> CanaryReport:
    """Score all planted-failure cases; default runner is a local shell check."""

    import subprocess

    def _default_runner(command: str, workdir: Path) -> bool:
        if not workdir.exists():
            return False
        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=workdir,
            capture_output=True,
            check=False,
        )
        return completed.returncode == 0

    cases = load_planted_failure_cases(root)
    score = runner or _default_runner
    results = [
        score_canary_case(case, runner=score, model_version=model_version) for case in cases
    ]
    return CanaryReport(
        model_version=model_version,
        trials=len(results),
        false_passes=sum(1 for r in results if r.false_pass),
    )
