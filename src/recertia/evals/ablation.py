"""T3 stratified control-arm sampler (specs §19, ADR-0005).

MUST NOT be imported from ``recertia.nodes`` or ``recertia.jobs`` — the boundary test enforces this.
Callers (CLI, harness, offline jobs) assign the arm and pass it into ``GraphOrchestrator.start``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from contracts.common import Arm

# Governed default; changing this rate is a T3 review (specs §22).
DEFAULT_ABLATION_RATE = 0.05


@dataclass(frozen=True)
class AblationDecision:
    arm: Arm
    reason: str
    rate: float
    eligible: bool


def assign_arm(
    *,
    run_id: str,
    task_class: str | None,
    seed: int | None = None,
    rate: float = DEFAULT_ABLATION_RATE,
    is_eval_fixture: bool = False,
    has_external_effects: bool = False,
    explicit_skill_supplied: bool = False,
) -> AblationDecision:
    """Stratified-by-task-class Bernoulli assignment with deterministic hashing.

    Exclusions (specs §19): eval fixtures, external effects, explicit caller-supplied skills.
    """

    if is_eval_fixture:
        return AblationDecision(
            arm="treatment",
            reason="eval fixture excluded from ablation",
            rate=rate,
            eligible=False,
        )
    if has_external_effects:
        return AblationDecision(
            arm="treatment",
            reason="external-effect task excluded from ablation",
            rate=rate,
            eligible=False,
        )
    if explicit_skill_supplied:
        return AblationDecision(
            arm="treatment",
            reason="explicit skill supplied; excluded from ablation",
            rate=rate,
            eligible=False,
        )
    if rate <= 0:
        return AblationDecision(
            arm="treatment", reason="ablation_rate<=0", rate=rate, eligible=True
        )
    if rate >= 1:
        return AblationDecision(
            arm="control", reason="ablation_rate>=1", rate=rate, eligible=True
        )

    material = f"{seed if seed is not None else ''}|{task_class or ''}|{run_id}"
    digest = hashlib.sha256(material.encode()).hexdigest()
    # Map first 8 hex digits into [0, 1).
    unit = int(digest[:8], 16) / 0xFFFFFFFF
    if unit < rate:
        return AblationDecision(
            arm="control",
            reason=f"sampled control (u={unit:.4f} < rate={rate})",
            rate=rate,
            eligible=True,
        )
    return AblationDecision(
        arm="treatment",
        reason=f"sampled treatment (u={unit:.4f} >= rate={rate})",
        rate=rate,
        eligible=True,
    )
