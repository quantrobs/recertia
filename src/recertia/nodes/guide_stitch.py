"""Deterministic ExecutionGuide stitch. Claim-conflict + order only; no LLM."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.guide import ExecutionGuide
from contracts.run import SkillCandidateRef
from recertia.solver.claims import ClaimScheduler


def stitch_guide(
    skills: list[SkillCandidateRef],
    *,
    claims_by_skill: dict[tuple[str, int], list] | None = None,
    now: datetime | None = None,
) -> ExecutionGuide | None:
    """Build a compact guide. Single-skill apply returns None."""

    if len(skills) < 2:
        return None
    claims_by_skill = claims_by_skill or {}
    ordered = sorted(skills, key=lambda s: (-s.score, s.skill_id))
    kept: list[SkillCandidateRef] = []
    avoided: list[str] = []
    held: list = []
    for skill in ordered:
        skill_claims = claims_by_skill.get((skill.skill_id, skill.version), [])
        conflict = any(
            ClaimScheduler.conflicts_with(a, b) for a in skill_claims for b in held
        )
        if conflict:
            avoided.append(f"{skill.skill_id}@v{skill.version}")
            continue
        kept.append(skill)
        held.extend(skill_claims)
    if not kept:
        kept = [ordered[0]]
        avoided = [f"{s.skill_id}@v{s.version}" for s in ordered[1:]]
    fallback = []
    unused = [s for s in ordered if s not in kept]
    if unused:
        fallback.append(f"{unused[0].skill_id}@v{unused[0].version}")
    return ExecutionGuide(
        primary=[f"{s.skill_id}@v{s.version}" for s in kept],
        checks=[],
        avoid=avoided,
        fallback=fallback,
        source_skills=[(s.skill_id, s.version) for s in kept],
        adapted_at=now or datetime.now(timezone.utc),
        method="deterministic_stitch",
    )


def reject_guide_leak(draft_text: str, guide: ExecutionGuide) -> str | None:
    """Builder firewall: guide strings must not be copied into a skill draft."""

    leaked = [
        fragment
        for fragment in (*guide.primary, *guide.avoid, *guide.fallback)
        if fragment and fragment in draft_text
    ]
    if leaked:
        return f"execution guide leaked into skill draft: {leaked[:3]}"
    return None
