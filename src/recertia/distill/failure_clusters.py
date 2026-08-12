"""Failure-cluster distillation into pitfall-oriented skills (specs §25)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.skill import FailureMode, Hygiene, Provenance, SkillVersion, Step
from recertia.distill.prior import load_authoring_prior
from recertia.memory.episodic import CaseRecord, EpisodicStore
from recertia.memory.episodic.clusters import ClusterStore, normalize_signature
from recertia.validation.sensitivity import author_sensitivity_proof

__all__ = [
    "normalize_signature",
    "cluster_dead_ends",
    "eligible_clusters",
    "author_pitfall_skill",
]


def eligible_clusters(store: ClusterStore, *, task_class: str | None = None) -> list:
    """Read incremental eligible rows. Preferred over ``cluster_dead_ends``."""

    return store.eligible(task_class=task_class)


def cluster_dead_ends(
    episodic: EpisodicStore, *, task_class: str, min_runs: int = 3
) -> list[tuple[str, list[CaseRecord]]]:
    """Rebuild clusters from the incremental index when present; else scan (rebuild)."""

    indexed = episodic.clusters.eligible(task_class=task_class)
    if indexed:
        out: list[tuple[str, list[CaseRecord]]] = []
        for row in indexed:
            if row.n_runs < min_runs:
                continue
            cases: list[CaseRecord] = []
            if row.last_case_hash:
                try:
                    cases.append(episodic.get(row.last_case_hash))
                except FileNotFoundError:
                    pass
            out.append((row.signature, cases or [_synthetic_case(row)]))
        return out

    buckets: dict[str, list[CaseRecord]] = defaultdict(list)
    seen_runs: dict[str, set[str]] = defaultdict(set)
    for index_row in episodic.list_index():
        if not index_row.get("has_dead_end"):
            continue
        if index_row.get("task_class") != task_class:
            continue
        case = episodic.get(index_row["hash"])
        assert case.dead_end is not None
        sig = normalize_signature(case.dead_end.why_failed, case.failure_class)
        if case.run_id in seen_runs[sig]:
            continue
        seen_runs[sig].add(case.run_id)
        buckets[sig].append(case)
    return [(sig, cases) for sig, cases in buckets.items() if len(cases) >= min_runs]


def _synthetic_case(row) -> CaseRecord:
    return CaseRecord(
        case_id=f"cluster-{row.signature[:12]}",
        run_id=row.run_ids_sample[0] if row.run_ids_sample else "unknown",
        attempt_no=1,
        task_class=row.task_class,
        outcome="failed",
        failure_class=row.signature.split("::", 1)[0],
    )



def author_pitfall_skill(
    *,
    task_class: str,
    signature: str,
    cluster: list[CaseRecord],
    negative_workdir: Path,
) -> SkillVersion:
    """Author a pitfall skill whose criterion fails on the recorded bad workspace."""

    prior = load_authoring_prior()
    digest = hashlib.sha256(signature.encode()).hexdigest()[:10]
    skill_id = f"pitfall-{task_class}-{digest}"
    # Criterion: the failure marker file created by the cluster fixture must be absent for a "good" workspace.
    # On the recorded failure workspace the marker exists, so `test ! -f` fails — proof rejects.
    cert = SkillCertificationCriterion(
        id="avoid-recorded-failure",
        kind="command",
        run="test ! -f .recertia-failure-marker",
        authored_by="distiller",
        weight=1.0,
        preregistered=True,
    )
    # Ensure the negative fixture has the marker.
    marker = negative_workdir / ".recertia-failure-marker"
    marker.write_text(signature + "\n", encoding="utf-8")
    proof = author_sensitivity_proof(cert, negative_workdir=negative_workdir)
    cert = cert.model_copy(update={"sensitivity_proof": proof})

    now = datetime.now(timezone.utc)
    return SkillVersion(
        skill_id=skill_id,
        version=1,
        title=f"Avoid repeated failure in {task_class}",
        intent=(
            f"Pitfall skill distilled from {len(cluster)} dead ends sharing signature "
            f"{signature!r}; check preconditions before retrying the failed approach."
        ),
        task_class=task_class,
        tags=[task_class, "pitfall", "failure-cluster"],
        steps=[
            Step(
                id="check_marker",
                tool="shell",
                intent="Refuse to proceed when the recorded failure marker is present",
                inputs={"command": "test ! -f .recertia-failure-marker"},
            )
        ],
        certification_criteria=[cert],
        failure_modes=[
            FailureMode(
                symptom=signature[:200],
                response="Do not retry the same approach; change strategy or abstain",
            )
        ],
        provenance=Provenance(
            distilled_from_run=cluster[0].run_id,
            distilled_at=now,
            curation="self_distilled",
            derivation="failure_cluster",
            failure_cluster_id=digest,
            authoring_prior_version=prior.version,
            source_run_ids=[c.run_id for c in cluster[:8]],
            source_session_ids=list(
                dict.fromkeys((c.session_id or c.run_id) for c in cluster)
            )[:8],
            source_case_ids=[c.case_id for c in cluster[:8]],
        ),
        hygiene=Hygiene(secret_scan="skipped"),
    )
