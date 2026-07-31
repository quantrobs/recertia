"""Reusability filter for distilled drafts (specs §7)."""

from __future__ import annotations

from contracts.run import ReusabilityVerdict
from contracts.skill import SkillVersion


def assess_reusability(
    version: SkillVersion,
    *,
    task_class_sightings: int = 1,
    near_duplicate_of: tuple[str, int] | None = None,
) -> ReusabilityVerdict:
    """Apply the five-gate reusability filter; near-duplicates are not ``reusable`` drafts."""

    parameterisable = bool(version.parameters) or task_class_sightings >= 3
    context_free = not any(
        "{{" in (step.inputs.get("command") or "") and "workdir" in str(step.inputs)
        for step in version.steps
    )
    # Simpler: no absolute /tmp paths baked in.
    context_free = all(
        "/tmp/" not in str(step.inputs.get("command", ""))
        and "/workspace/" not in str(step.inputs.get("command", ""))
        for step in version.steps
    )
    checkable = any(
        c.kind != "judge" and c.is_required and c.is_preregistered_and_proven
        for c in version.certification_criteria
    )
    not_duplicate = near_duplicate_of is None
    bounded = all(
        step.loop is None or step.loop.max_iterations <= 10 for step in version.steps
    ) and len(version.steps) <= 12

    reasons: list[str] = []
    if not parameterisable:
        reasons.append("not parameterisable and task class seen fewer than 3 times")
    if not context_free:
        reasons.append("steps embed machine-local absolute paths")
    if not checkable:
        reasons.append("no required non-judge criterion with rejecting sensitivity proof")
    if not not_duplicate:
        reasons.append(
            f"near-duplicate of {near_duplicate_of[0]}@v{near_duplicate_of[1]}"
            if near_duplicate_of is not None
            else "near-duplicate"
        )
    if not bounded:
        reasons.append("unbounded loop or too many steps")

    ok = parameterisable and context_free and checkable and not_duplicate and bounded
    if near_duplicate_of is not None and parameterisable and context_free and checkable and bounded:
        verdict = "duplicate"
        reason = f"route as new version of {near_duplicate_of[0]}@v{near_duplicate_of[1]}"
    elif ok:
        verdict = "reusable"
        reason = "passes reusability filter"
    else:
        verdict = "one_off"
        reason = "; ".join(reasons) or "reusability filter failed"

    return ReusabilityVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        parameterisable=parameterisable,
        context_free=context_free,
        checkable=checkable,
        not_duplicate=not_duplicate,
        bounded=bounded,
        reason=reason,
    )
