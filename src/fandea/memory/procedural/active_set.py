"""Bounded active set per task class (specs §24.1, M5)."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.common import RETRIEVABLE_LIFECYCLES
from contracts.status import SkillStatus
from fandea.evals.store import EvalStore
from fandea.memory.procedural.contribution import estimate_contribution
from fandea.memory.procedural.store import SkillStore
from fandea.review.autonomy_config import DEFAULT_AUTONOMY, AutonomyConfig


def assign_active_on_approval(status: SkillStatus) -> SkillStatus:
    """Mark approved versions active; shadow stays inactive for direct application."""

    if status.lifecycle == "approved":
        return status.model_copy(update={"active": True})
    if status.lifecycle in RETRIEVABLE_LIFECYCLES:
        return status.model_copy(update={"active": False})
    return status.model_copy(update={"active": False})


def recompute_active_set(
    store: SkillStore,
    *,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    eval_store: EvalStore | None = None,
) -> tuple[list[SkillStatus], dict[str, float]]:
    """Cap approved actives using persisted non-judge treatment/control evidence.

    Returns ``(updated_statuses, active_cap_pressure_by_task_class)`` where pressure is
    ``max(0, approved_count - cap) / cap``.
    """

    by_class: dict[str, list[tuple]] = {}
    for version, status, stats in store.iter_loaded():
        by_class.setdefault(version.task_class, []).append((version, status, stats))

    updated: list[SkillStatus] = []
    pressure: dict[str, float] = {}
    for task_class, rows in by_class.items():
        approved = [(v, s, st) for v, s, st in rows if s.lifecycle == "approved"]
        evidenced: list[tuple] = []
        if eval_store is not None:
            for version, status, stats in approved:
                treatment, control = eval_store.contribution_samples(
                    skill_id=version.skill_id,
                    version=version.version,
                    task_class=task_class,
                )
                contribution = estimate_contribution(
                    applications=treatment.trials,
                    successes=treatment.successes,
                    control=control,
                )
                if contribution != stats.contribution:
                    store.write_stats(stats.model_copy(update={"contribution": contribution}))
                if contribution.estimate is not None:
                    evidenced.append((version, status, stats.model_copy(update={"contribution": contribution})))
        # Rank: contribution estimate (None → -inf), then trust score.
        def rank(row: tuple) -> tuple[float, float]:
            _v, _s, st = row
            est = st.contribution.estimate
            trust = (st.trust.successes + 1) / (st.trust.applications + 2)
            return (est if est is not None else float("-inf"), trust)

        evidenced.sort(key=rank, reverse=True)
        cap = config.active_cap_per_task_class
        pressure[task_class] = max(0, len(approved) - cap) / cap if cap else 0.0
        top = evidenced[:cap]

        for version, status, stats in rows:
            if status.lifecycle == "approved":
                want_active = any(
                    kept_v.skill_id == version.skill_id and kept_v.version == version.version
                    for kept_v, _s, _st in top
                )
                new_status = status.model_copy(update={"active": want_active})
            else:
                new_status = assign_active_on_approval(status)
            if new_status != status:
                store.write_status(new_status)
            updated.append(new_status)
    return updated, pressure


def now() -> datetime:
    return datetime.now(timezone.utc)
