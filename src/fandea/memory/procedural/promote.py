"""Promote a skill to ``approved`` only after its golden regression gate passes (specs §8).

The regression runner's log is the evidence — recorded on ``SkillStatus.certification`` —
not a note in a PR description. M4: the gate may run the full task-class harness and must
name every failing fixture id on refusal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.skill import SkillVersion
from contracts.status import Certification, SkillStatus
from fandea.evals.golden import (
    GoldenReport,
    GoldenResult,
    run_golden_for_skill,
    run_task_class_gate,
)
from fandea.memory.procedural.active_set import assign_active_on_approval
from fandea.memory.procedural.lint import lint_skill
from fandea.memory.procedural.store import SkillStore


class PromotionError(Exception):
    """Golden gate failed, or the skill is not yet eligible for approval."""

    def __init__(self, message: str, *, failing_fixtures: list[str] | None = None) -> None:
        super().__init__(message)
        self.failing_fixtures = failing_fixtures or []


def promote_to_approved(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    golden_dir: Path | None = None,
    golden_root: Path | None = None,
    runs_root: Path,
    log_dir: Path,
    model_validated_on: str = "m1-seed",
    tool_fingerprint: dict[str, str] | None = None,
    repo_root: Path | None = None,
    require_task_class_gate: bool = False,
) -> SkillStatus:
    """Run golden regression; on pass, write ``lifecycle=approved, active=True`` and the log ref.

    Prefer ``golden_root`` + task-class harness when ``require_task_class_gate`` is set (M4).
    Otherwise a single ``golden_dir`` preserves the M1 seed-promotion path.
    """

    ver = store.get_version(skill_id, version)
    status = store.get_status(skill_id, version)
    stats = store.get_stats(skill_id, version)

    candidate_status = status.model_copy(update={"lifecycle": "candidate"})
    violations = lint_skill(ver, candidate_status, stats, store=store)
    if violations:
        raise PromotionError(f"skill not eligible for approval: {violations}")

    report = _run_regression(
        ver,
        golden_dir=golden_dir,
        golden_root=golden_root,
        runs_root=runs_root,
        require_task_class_gate=require_task_class_gate,
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{skill_id}-v{version}.json"
    log_path.write_text(_report_json(report), encoding="utf-8")

    if not report.all_passed:
        failing = [
            Path(r.golden_path).name or r.skill_id for r in report.results if not r.passed
        ]
        raise PromotionError(
            f"golden gate failed for {skill_id}@v{version}: "
            f"failing fixtures={failing} (log: {log_path})",
            failing_fixtures=failing,
        )

    golden_ref = _portable_ref(log_path, repo_root)

    approved = SkillStatus(
        skill_id=skill_id,
        version=version,
        lifecycle="approved",
        active=False,
        certification=Certification(
            model_validated_on=model_validated_on,
            tool_fingerprint=tool_fingerprint or {},
            golden_set_ref=golden_ref,
            last_recertified_at=datetime.now(timezone.utc),
            recert_status="fresh",
        ),
    )
    approved = assign_active_on_approval(approved)
    violations = lint_skill(ver, approved, stats, store=store)
    if violations:
        raise PromotionError(f"approved profile violations: {violations}")
    store.write_status(approved)
    return approved


def _run_regression(
    ver: SkillVersion,
    *,
    golden_dir: Path | None,
    golden_root: Path | None,
    runs_root: Path,
    require_task_class_gate: bool,
) -> GoldenReport:
    if require_task_class_gate or (golden_root is not None and golden_dir is None):
        if golden_root is None:
            raise PromotionError("task-class regression gate requires golden_root")
        report = run_task_class_gate(
            ver, golden_root, runs_root=runs_root, task_class=ver.task_class
        )
        if golden_dir is not None and golden_dir.is_dir():
            own = run_golden_for_skill(ver, golden_dir, runs_root=runs_root)
            if not any(r.golden_path == own.golden_path for r in report.results):
                report.results.append(own)
        return report

    if golden_dir is None:
        raise PromotionError("promote_to_approved requires golden_dir or golden_root")
    result = run_golden_for_skill(ver, golden_dir, runs_root=runs_root)
    return GoldenReport(results=[result])


def _portable_ref(log_path: Path, repo_root: Path | None) -> str:
    resolved = log_path.resolve()
    if repo_root is not None:
        try:
            return resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            pass
    parts = resolved.parts
    if "evals" in parts:
        idx = parts.index("evals")
        return "/".join(parts[idx:])
    return str(resolved)


def _report_json(report: GoldenReport) -> str:
    import json
    from dataclasses import asdict

    results: list[dict] = []
    for result in report.results:
        row = asdict(result)
        row["at"] = result.at.isoformat()
        results.append(row)
    payload = {"all_passed": report.all_passed, "results": results}
    return json.dumps(payload, indent=2) + "\n"


def _result_json(result: GoldenResult) -> str:
    """Backward-compatible helper for callers that still log a single result."""

    report = GoldenReport(results=[result])
    return _report_json(report)
