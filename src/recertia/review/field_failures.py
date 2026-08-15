"""Field-failure off-ramp: Recertifier reads across runs and quarantines (ADR-0008).

A single run must never mark a stored version ``quarantined``. Consecutive treatment-arm
failures where the skill was applied are aggregate evidence the Recertifier consumes.
"""

from __future__ import annotations

from dataclasses import dataclass

from recertia.evals.store import EvalStore
from recertia.ledger import HashChainLedger
from recertia.memory.procedural.store import SkillStore
from recertia.review.autonomy_config import DEFAULT_AUTONOMY, AutonomyConfig
from recertia.review.lifecycle import quarantine_on_failures


@dataclass(frozen=True)
class FieldOffRamp:
    skill_id: str
    version: int
    consecutive_failures: int


def recertify_field_failures(
    store: SkillStore,
    eval_store: EvalStore,
    *,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    ledger: HashChainLedger | None = None,
) -> list[FieldOffRamp]:
    """Quarantine approved versions with a trailing field-failure streak at the threshold."""

    streaks = eval_store.field_failure_streaks()
    off_ramps: list[FieldOffRamp] = []
    for version, status, _stats in store.iter_loaded():
        if status.lifecycle not in {"approved", "shadow", "needs_recert"}:
            continue
        streak = streaks.get((version.skill_id, version.version), 0)
        if streak < config.quarantine_consecutive_failures:
            continue
        quarantined = quarantine_on_failures(
            store,
            version.skill_id,
            version.version,
            consecutive_failures=streak,
            config=config,
            ledger=ledger,
        )
        if quarantined.lifecycle != "quarantined":
            continue
        off_ramps.append(
            FieldOffRamp(
                skill_id=version.skill_id,
                version=version.version,
                consecutive_failures=streak,
            )
        )
    return off_ramps
