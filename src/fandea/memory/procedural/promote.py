"""Promote a skill to ``approved`` only after its golden task passes (specs §8).

The regression runner's log is the evidence — recorded on ``SkillStatus.certification`` —
not a note in a PR description.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.status import Certification, SkillStatus
from fandea.evals.golden import GoldenResult, run_golden_for_skill
from fandea.memory.procedural.active_set import assign_active_on_approval
from fandea.memory.procedural.lint import lint_skill
from fandea.memory.procedural.store import SkillStore


class PromotionError(Exception):
    """Golden gate failed, or the skill is not yet eligible for approval."""


def promote_to_approved(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    golden_dir: Path,
    runs_root: Path,
    log_dir: Path,
    model_validated_on: str = "m1-seed",
    tool_fingerprint: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> SkillStatus:
    """Run the golden task; on pass, write ``lifecycle=approved, active=True`` and the log ref.

    ``golden_set_ref`` is stored as a path relative to ``repo_root`` (when provided) so the
    evidence travels with the repository and resolves on any checkout — not as an absolute
    machine-local path that breaks CI.
    """

    ver = store.get_version(skill_id, version)
    status = store.get_status(skill_id, version)
    stats = store.get_stats(skill_id, version)

    # Pre-approval lint against the candidate profile (lifecycle may still be draft/candidate).
    candidate_status = status.model_copy(update={"lifecycle": "candidate"})
    violations = lint_skill(ver, candidate_status, stats, store=store)
    if violations:
        raise PromotionError(f"skill not eligible for approval: {violations}")

    result = run_golden_for_skill(ver, golden_dir, runs_root=runs_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{skill_id}-v{version}.json"
    log_path.write_text(_result_json(result), encoding="utf-8")
    if not result.passed:
        raise PromotionError(
            f"golden gate failed for {skill_id}@v{version}: {result.detail} "
            f"(log: {log_path})"
        )

    golden_ref = _portable_ref(log_path, repo_root)

    approved = SkillStatus(
        skill_id=skill_id,
        version=version,
        lifecycle="approved",
        active=False,  # assign_active_on_approval sets it
        certification=Certification(
            model_validated_on=model_validated_on,
            tool_fingerprint=tool_fingerprint or {},
            golden_set_ref=golden_ref,
            last_recertified_at=datetime.now(timezone.utc),
            recert_status="fresh",
        ),
    )
    approved = assign_active_on_approval(approved)
    # Final approved-skill profile check.
    violations = lint_skill(ver, approved, stats, store=store)
    if violations:
        raise PromotionError(f"approved profile violations: {violations}")
    store.write_status(approved)
    return approved


def _portable_ref(log_path: Path, repo_root: Path | None) -> str:
    """Prefer a repo-relative POSIX path; fall back to the absolute path only if needed."""

    resolved = log_path.resolve()
    if repo_root is not None:
        try:
            return resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            pass
    # Best-effort: if the path contains the canonical evals/golden prefix, strip to that.
    parts = resolved.parts
    if "evals" in parts:
        idx = parts.index("evals")
        return "/".join(parts[idx:])
    return str(resolved)


def _result_json(result: GoldenResult) -> str:
    import json
    from dataclasses import asdict

    payload = asdict(result)
    payload["at"] = result.at.isoformat()
    return json.dumps(payload, indent=2) + "\n"
