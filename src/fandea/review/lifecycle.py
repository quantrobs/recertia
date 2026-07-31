"""Lifecycle transitions: shadow promote, quarantine, bench/restore (M5)."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.status import Retirement, SkillStatus
from fandea.evals.store import EvalStore
from fandea.ledger import HashChainLedger
from fandea.memory.procedural.contribution import (
    estimate_contribution,
    estimate_retrieval_ablation,
    trust_score,
)
from fandea.memory.procedural.store import SkillStore
from fandea.review.autonomy_config import DEFAULT_AUTONOMY, AutonomyConfig


class LifecycleError(Exception):
    """Illegal or refused lifecycle transition."""


def maybe_advance_shadow_to_candidate(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    eval_store: EvalStore,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    ledger: HashChainLedger | None = None,
) -> SkillStatus:
    """Advance shadow → candidate when lift and sample thresholds clear (no human).

    Does not write ``approved``; golden-gated ``promote_to_approved`` remains required.
    """

    status = store.get_status(skill_id, version)
    if status.lifecycle != "shadow":
        raise LifecycleError(f"{skill_id}@v{version} is {status.lifecycle}, not shadow")
    stats = store.get_stats(skill_id, version)
    trust = trust_score(
        applications=stats.predictive_trust.applications,
        successes=stats.predictive_trust.successes,
    )
    task_class = store.get_version(skill_id, version).task_class
    shadow, suppression = eval_store.contribution_samples(
        skill_id=skill_id,
        version=version,
        task_class=task_class,
    )
    contrib = estimate_contribution(
        shadow=shadow,
        suppression=suppression,
    )
    # High trust + zero/None lift must NOT auto-promote.
    lift = contrib.estimate
    if lift is None or lift < config.shadow_min_lift:
        raise LifecycleError(
            f"refusing auto-promote: lift={lift} trust={trust:.3f} "
            f"(need lift>={config.shadow_min_lift})"
        )
    if shadow.trials < config.shadow_min_applications:
        raise LifecycleError("insufficient shadow applications")
    if shadow.successes < config.shadow_min_successes:
        raise LifecycleError("insufficient shadow successes")

    # Curation prior: self_distilled needs higher lift.
    version_doc = store.get_version(skill_id, version)
    required_lift = config.shadow_min_lift
    if version_doc.provenance.curation == "self_distilled":
        required_lift = config.shadow_min_lift / config.curation_prior_self_distilled
    if lift < required_lift:
        raise LifecycleError(f"self_distilled bar not met: lift={lift} need>={required_lift}")

    # Shadow evidence makes this version eligible for the golden-gated
    # promotion service; it is not itself an approval authority.
    candidate = status.model_copy(update={"lifecycle": "candidate", "active": False})
    store.write_status(candidate, expected_lifecycle=status.lifecycle)
    enabled, retrieval_suppressed = eval_store.retrieval_ablation_samples(task_class=task_class)
    eval_store.write_retrieval_ablation(
        estimate_retrieval_ablation(
            task_class=task_class,
            retrieval_enabled=enabled,
            retrieval_suppressed=retrieval_suppressed,
        )
    )
    store.write_stats(
        stats.model_copy(
            update={
                "predictive_trust": stats.predictive_trust.model_copy(
                    update={"decayed_score": trust}
                ),
                "contribution": contrib,
            }
        )
    )
    if ledger is not None:
        ledger.append(
            actor="m5-shadow-autonomy",
            action="advance_to_candidate",
            target=f"{skill_id}@v{version}",
            evidence={"lift": lift, "trust": trust, "path": "shadow"},
            at=datetime.now(timezone.utc),
        )
    return candidate


def maybe_auto_promote_from_shadow(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    eval_store: EvalStore,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    ledger: HashChainLedger | None = None,
) -> SkillStatus:
    """Deprecated alias for :func:`maybe_advance_shadow_to_candidate`.

    Prefer ``maybe_advance_shadow_to_candidate`` — this advances shadow → candidate only;
    golden-gated ``promote_to_approved`` remains required for ``approved``.
    """

    return maybe_advance_shadow_to_candidate(
        store,
        skill_id,
        version,
        eval_store=eval_store,
        config=config,
        ledger=ledger,
    )


def quarantine_on_failures(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    consecutive_failures: int,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    ledger: HashChainLedger | None = None,
) -> SkillStatus:
    status = store.get_status(skill_id, version)
    if consecutive_failures < config.quarantine_consecutive_failures:
        return status
    quarantined = status.model_copy(update={"lifecycle": "quarantined", "active": False})
    store.write_status(quarantined, expected_lifecycle=status.lifecycle)
    if ledger is not None:
        ledger.append(
            actor="m5-quarantine",
            action="quarantine_version",
            target=f"{skill_id}@v{version}",
            evidence={"consecutive_failures": consecutive_failures},
            at=datetime.now(timezone.utc),
        )
    return quarantined


def maybe_bench_on_contribution(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    eval_store: EvalStore,
    config: AutonomyConfig = DEFAULT_AUTONOMY,
    ledger: HashChainLedger | None = None,
) -> SkillStatus:
    """Bench when contribution is sustainably negative past the evidence floor."""

    status = store.get_status(skill_id, version)
    stats = store.get_stats(skill_id, version)
    task_class = store.get_version(skill_id, version).task_class
    shadow, suppression = eval_store.contribution_samples(
        skill_id=skill_id,
        version=version,
        task_class=task_class,
    )
    apps = shadow.trials
    if apps < config.evidence_floor:
        raise LifecycleError(
            f"below evidence floor ({apps} < {config.evidence_floor}); never bench"
        )
    contrib = estimate_contribution(
        shadow=shadow, suppression=suppression
    )
    est = contrib.estimate
    if est is None or est > -config.retirement_threshold:
        raise LifecycleError(f"contribution not negative enough: estimate={est}")
    benched = status.model_copy(
        update={
            "lifecycle": "benched",
            "active": False,
            "retirement": Retirement(
                benched_at=datetime.now(timezone.utc),
                reason="negative_contribution",
                evidence=f"estimate={est}",
            ),
        }
    )
    store.write_status(benched, expected_lifecycle=status.lifecycle)
    enabled, retrieval_suppressed = eval_store.retrieval_ablation_samples(task_class=task_class)
    eval_store.write_retrieval_ablation(
        estimate_retrieval_ablation(
            task_class=task_class,
            retrieval_enabled=enabled,
            retrieval_suppressed=retrieval_suppressed,
        )
    )
    store.write_stats(
        stats.model_copy(update={"contribution": contrib})
    )
    if ledger is not None:
        ledger.append(
            actor="m5-retirement",
            action="deprecate",
            target=f"{skill_id}@v{version}",
            evidence={"estimate": est, "state": "benched"},
            at=datetime.now(timezone.utc),
        )
    # Parents of a benched child → needs_recert (M5 + M8).
    _mark_parents_needs_recert(store, skill_id, version, ledger=ledger)
    return benched


def restore_benched(
    store: SkillStore,
    skill_id: str,
    version: int,
    *,
    ledger: HashChainLedger | None = None,
) -> SkillStatus:
    status = store.get_status(skill_id, version)
    if status.lifecycle != "benched":
        raise LifecycleError("only benched skills can be restored")
    # Restoring availability requires fresh independent regression evidence.
    # The golden promotion service is the only authority that may transition
    # this candidate to approved.
    restored = status.model_copy(
        update={
            "lifecycle": "candidate",
            "active": False,
            "retirement": status.retirement.model_copy(
                update={"restored_at": datetime.now(timezone.utc)}
            ),
        }
    )
    store.write_status(restored, expected_lifecycle="benched")
    if ledger is not None:
        ledger.append(
            actor="m5-retirement",
            action="policy_change",
            target=f"{skill_id}@v{version}",
            evidence={"state": "restored"},
            at=datetime.now(timezone.utc),
        )
    return restored


def _mark_parents_needs_recert(
    store: SkillStore,
    child_id: str,
    child_version: int,
    *,
    ledger: HashChainLedger | None,
) -> None:
    for version, status, _stats in store.iter_loaded():
        if any(u.skill_id == child_id and u.version == child_version for u in version.uses):
            if status.lifecycle in ("approved", "shadow"):
                store.write_status(
                    status.model_copy(update={"lifecycle": "needs_recert", "active": False}),
                    expected_lifecycle=status.lifecycle,
                )
                if ledger is not None:
                    ledger.append(
                        actor="m5-retirement",
                        action="policy_change",
                        target=f"{version.skill_id}@v{version.version}",
                        evidence={
                            "reason": "child_benched",
                            "child": f"{child_id}@v{child_version}",
                        },
                        at=datetime.now(timezone.utc),
                    )
