"""Semantic profiles: the MUSTs a structural schema cannot express (ADR-0009; refactor-plan B5).

Each profile is a function returning a list of violation strings — empty means the object
passes. These are what CI runs against canonical examples, not merely ``model_validate``.
"""

from __future__ import annotations

from contracts.run import RunState
from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus


def validate_candidate_skill(version: SkillVersion, status: SkillStatus) -> list[str]:
    """MUSTs for a version to legitimately hold ``lifecycle == 'candidate'`` (specs §2.1, §15)."""

    violations: list[str] = []
    if status.skill_id != version.skill_id or status.version != version.version:
        violations.append("status does not key to this version")
    if status.lifecycle not in ("candidate", "shadow", "approved"):
        # candidate-skill profile also covers versions that have progressed past candidate.
        violations.append(f"lifecycle {status.lifecycle!r} never reached candidate")
    required = [c for c in version.certification_criteria if c.is_required]
    if not required:
        violations.append("no required certification criteria; cannot reach candidate (specs §15.2)")
    if not any(c.is_preregistered_and_proven for c in required):
        violations.append(
            "no required criterion has a valid, rejecting sensitivity proof (specs §15.2)"
        )
    if version.hygiene.secret_scan != "passed":
        violations.append("hygiene.secret_scan MUST be 'passed' before a version may be stored")
    return violations


def validate_approved_skill(
    version: SkillVersion, status: SkillStatus, stats: SkillStats
) -> list[str]:
    """MUSTs for a version to legitimately hold ``lifecycle == 'approved'`` (specs §2.1, §8, §24)."""

    violations = validate_candidate_skill(version, status)
    if status.lifecycle != "approved":
        violations.append(f"lifecycle is {status.lifecycle!r}, not approved")
    if all(c.kind == "judge" for c in version.certification_criteria):
        violations.append(
            "a judge-only skill MUST NOT reach approved (specs §2.1); "
            "contribution would be null under the Blind Curator fix (references.md §1.8)"
        )
    if status.certification.model_validated_on is None:
        violations.append("certification.model_validated_on MUST be recorded before approval")
    if version.provenance.curation == "self_distilled":
        # Higher evidence bar for self-distilled skills (ADR-0006 §6): at minimum, some
        # applications must have been observed before promotion can be considered earned.
        if stats.predictive_trust.applications == 0 and status.certification.recert_status == "never":
            violations.append(
                "self_distilled skill approved with zero observed applications and no "
                "certification run; higher evidence bar (ADR-0006) not demonstrated"
            )
    if status.active and status.lifecycle != "approved":
        violations.append("active=True requires lifecycle == 'approved'")
    for use in version.uses:
        if use.skill_id == version.skill_id:
            violations.append("uses graph MUST NOT reference the parent skill itself (cycle)")
    return violations


def validate_checkpointed_run(state: RunState) -> list[str]:
    """MUSTs for a ``RunState`` that has passed ``intake`` to be a valid checkpoint (specs §3, §15.1)."""

    violations: list[str] = []
    if state.criteria and state.criteria_locked_at is None:
        violations.append("criteria present but criteria_locked_at is unset")
    if state.manifest.criteria_hash is None and state.criteria_locked_at is not None:
        violations.append("criteria_locked_at set but manifest.criteria_hash is missing")
    if state.arm == "control" and not state.bundle.suppressed:
        violations.append("arm='control' MUST suppress the bundle (specs §5, §11.4)")
    if state.terminal is not None and not state.route_log:
        violations.append("a terminal run MUST have a non-empty route_log (specs §12)")
    for branch in state.branches:
        if branch.kind == "decomposition" and not branch.owned_criteria and branch.status in (
            "succeeded",
            "running",
        ):
            violations.append(
                f"decomposition branch {branch.branch_id!r} owns no criteria (specs §18)"
            )
    for b in state.branches:
        if b.budget.max_wall_clock_s > state.budget.max_wall_clock_s:
            violations.append(
                f"branch {b.branch_id!r} budget exceeds the parent budget it must divide "
                "(specs §18: 'a division of the parent budget, never a multiple')"
            )
    return violations
