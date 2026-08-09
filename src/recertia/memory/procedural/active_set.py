"""Bounded active set per task class (specs §24.1, M5).

``recompute_active_set`` currently carries two implementations of the same behavior. The
legacy one is the code that shipped; the other delegates ranking, selection, and retirement
proposals to the pure controller in :mod:`recertia.memory.procedural.portfolio`. Which one
runs is decided by the ``RECERTIA_PORTFOLIO_CONTROLLER`` environment flag.

That flag is scaffolding for the equivalence proof, not a tunable. A switch that changes
which skills are retrievable is measurement semantics, which ADR-0005 places at T3, so it
MUST NOT be offered as user-facing configuration or documented as such. Both the flag and
``_recompute_active_set_legacy`` are to be **deleted at the end of Phase 2**, once the
measurement report exists and the pure path is the only path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from contracts.common import RETRIEVABLE_LIFECYCLES
from contracts.eval import BinomialSample
from contracts.status import SkillStatus
from recertia.evals.store import EvalStore
from recertia.memory.procedural.contribution import (
    estimate_contribution,
    estimate_retrieval_ablation,
)
from recertia.memory.procedural.portfolio import rank_skills, select_active
from recertia.memory.procedural.store import SkillStore
from recertia.review.autonomy_config import DEFAULT_AUTONOMY, AutonomyConfig


def assign_active_on_approval(status: SkillStatus) -> SkillStatus:
    """Mark approved versions active; shadow stays inactive for direct application."""

    if status.lifecycle == "approved":
        return status.model_copy(update={"active": True})
    if status.lifecycle in RETRIEVABLE_LIFECYCLES:
        return status.model_copy(update={"active": False})
    return status.model_copy(update={"active": False})


@dataclass(frozen=True)
class ShadowSlot:
    """An offline-only evaluation assignment, never an active retrieval slot."""

    skill_id: str
    version: int
    task_class: str
    reason: str


def select_shadow_slots(
    store: SkillStore, *, config: AutonomyConfig = DEFAULT_AUTONOMY
) -> list[ShadowSlot]:
    """Allocate bounded offline slots to benched and inactive approved versions.

    These slots do not alter ``SkillStatus.active`` and therefore cannot expand
    the caller-visible active cap.
    """

    by_class: dict[str, list[tuple]] = {}
    for version, status, stats in store.iter_loaded():
        if status.lifecycle == "benched" or (
            status.lifecycle == "approved" and not status.active
        ):
            by_class.setdefault(version.task_class, []).append((version, status, stats))
    slots: list[ShadowSlot] = []
    for task_class, rows in by_class.items():
        rows.sort(
            key=lambda row: (
                row[2].contribution.applications + row[2].contribution.suppressed_applications,
                row[0].skill_id,
                row[0].version,
            )
        )
        for version, status, _stats in rows[: config.shadow_slots_per_task_class]:
            slots.append(
                ShadowSlot(
                    skill_id=version.skill_id,
                    version=version.version,
                    task_class=task_class,
                    reason="benched" if status.lifecycle == "benched" else "newly_approved",
                )
            )
    return slots


def _portfolio_controller_enabled() -> bool:
    """Temporary Phase 1 flag; removed with the legacy branch at the end of Phase 2."""

    return os.environ.get("RECERTIA_PORTFOLIO_CONTROLLER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def recompute_active_set(
    store: SkillStore,
    *,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    eval_store: EvalStore | None = None,
) -> tuple[list[SkillStatus], dict[str, float]]:
    """Cap approved actives using persisted non-judge treatment/control evidence.

    Returns ``(updated_statuses, active_cap_pressure_by_task_class)`` where pressure is
    ``max(0, approved_count - cap) / cap``.

    Both branches below are required to produce identical statuses, pressure, and writes;
    the flag exists only so that equivalence can be asserted in CI (see module docstring).
    """

    if _portfolio_controller_enabled():
        return _recompute_active_set_portfolio(store, config=config, eval_store=eval_store)
    return _recompute_active_set_legacy(store, config=config, eval_store=eval_store)


def _recompute_active_set_legacy(
    store: SkillStore,
    *,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    eval_store: EvalStore | None = None,
) -> tuple[list[SkillStatus], dict[str, float]]:
    """The pre-controller implementation, kept verbatim as the equivalence reference."""

    by_class: dict[str, list[tuple]] = {}
    for version, status, stats in store.iter_loaded():
        by_class.setdefault(version.task_class, []).append((version, status, stats))

    empty_sample = BinomialSample(successes=0, trials=0)
    updated: list[SkillStatus] = []
    pressure: dict[str, float] = {}
    for task_class, rows in by_class.items():
        approved = [(v, s, st) for v, s, st in rows if s.lifecycle == "approved"]
        evidenced: list[tuple] = []
        if eval_store is not None:
            retrieval_enabled, retrieval_suppressed = eval_store.retrieval_ablation_samples(
                task_class=task_class
            )
            retrieval_ablation = estimate_retrieval_ablation(
                task_class=task_class,
                retrieval_enabled=retrieval_enabled,
                retrieval_suppressed=retrieval_suppressed,
            )
            eval_store.write_retrieval_ablation(retrieval_ablation)
            # Two grouped scans for the whole class instead of two queries per skill.
            samples = eval_store.contribution_samples_bulk(task_class=task_class)
            for version, status, stats in approved:
                shadow, suppression = samples.get(
                    (version.skill_id, version.version),
                    (empty_sample, empty_sample),
                )
                contribution = estimate_contribution(
                    shadow=shadow,
                    suppression=suppression,
                )
                updated_stats = stats.model_copy(update={"contribution": contribution})
                if updated_stats != stats:
                    store.write_stats(updated_stats)
                if contribution.estimate is not None:
                    evidenced.append((version, status, updated_stats))
        if not evidenced:
            # Without fresh eval evidence, rank from persisted stats so a curator
            # pass cannot empty the active set.
            evidenced = list(approved)

        # Rank: contribution estimate (None → -inf), then trust score.
        def rank(row: tuple) -> tuple[float, float]:
            _v, _s, st = row
            est = st.contribution.estimate
            trust = st.predictive_trust.score
            return (est if est is not None else float("-inf"), trust)

        evidenced.sort(key=rank, reverse=True)
        cap = config.active_cap_per_task_class
        pressure[task_class] = max(0, len(approved) - cap) / cap if cap else 0.0
        top_ids = {(v.skill_id, v.version) for v, _s, _st in evidenced[:cap]}

        for version, status, stats in rows:
            if status.lifecycle == "approved":
                want_active = (version.skill_id, version.version) in top_ids
                new_status = status.model_copy(update={"active": want_active})
            else:
                new_status = assign_active_on_approval(status)
            if new_status != status:
                store.write_status(new_status)
            updated.append(new_status)
    return updated, pressure


def _recompute_active_set_portfolio(
    store: SkillStore,
    *,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    eval_store: EvalStore | None = None,
) -> tuple[list[SkillStatus], dict[str, float]]:
    """Same contract as the legacy path, with ranking delegated to the pure controller.

    Candidate selection, the refreshed-contribution writes, and the active-bit writes are
    unchanged; only the ordering and the top-``cap`` cut move into
    :mod:`recertia.memory.procedural.portfolio`.

    Candidates are still narrowed to skills with a fresh, non-``None`` estimate when an
    ``eval_store`` is supplied. That narrowing is a property of *this* orchestrator, not of
    ``rank_skills``, which keeps below-floor and ``None``-estimate skills in the pool as
    FR-2 requires.

    ``propose_retirements`` is deliberately not called here: nothing in this function may
    bench a skill. Wiring the proposer into the Curator is Phase 5.
    """

    by_class: dict[str, list[tuple]] = {}
    for version, status, stats in store.iter_loaded():
        by_class.setdefault(version.task_class, []).append((version, status, stats))

    empty_sample = BinomialSample(successes=0, trials=0)
    updated: list[SkillStatus] = []
    pressure: dict[str, float] = {}
    for task_class, rows in by_class.items():
        approved = [(v, s, st) for v, s, st in rows if s.lifecycle == "approved"]
        candidates: list[tuple] = []
        if eval_store is not None:
            retrieval_enabled, retrieval_suppressed = eval_store.retrieval_ablation_samples(
                task_class=task_class
            )
            retrieval_ablation = estimate_retrieval_ablation(
                task_class=task_class,
                retrieval_enabled=retrieval_enabled,
                retrieval_suppressed=retrieval_suppressed,
            )
            eval_store.write_retrieval_ablation(retrieval_ablation)
            # Two grouped scans for the whole class instead of two queries per skill.
            samples = eval_store.contribution_samples_bulk(task_class=task_class)
            for version, status, stats in approved:
                shadow, suppression = samples.get(
                    (version.skill_id, version.version),
                    (empty_sample, empty_sample),
                )
                contribution = estimate_contribution(
                    shadow=shadow,
                    suppression=suppression,
                )
                updated_stats = stats.model_copy(update={"contribution": contribution})
                if updated_stats != stats:
                    store.write_stats(updated_stats)
                if contribution.estimate is not None:
                    candidates.append((version, status, updated_stats))
        if not candidates:
            # Without fresh eval evidence, rank from persisted stats so a curator
            # pass cannot empty the active set.
            candidates = list(approved)

        cap = config.active_cap_per_task_class
        pressure[task_class] = max(0, len(approved) - cap) / cap if cap else 0.0
        top_ids = select_active(rank_skills(candidates, config), cap)

        for version, status, stats in rows:
            if status.lifecycle == "approved":
                want_active = (version.skill_id, version.version) in top_ids
                new_status = status.model_copy(update={"active": want_active})
            else:
                new_status = assign_active_on_approval(status)
            if new_status != status:
                store.write_status(new_status)
            updated.append(new_status)
    return updated, pressure


def now() -> datetime:
    return datetime.now(timezone.utc)
