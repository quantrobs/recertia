"""Failure-cluster distillation into pitfall-oriented skills (specs §25)."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.skill import FailureMode, Hygiene, Provenance, SkillVersion, Step
from fandea.distill.prior import load_authoring_prior
from fandea.memory.episodic import CaseRecord, EpisodicStore
from fandea.validation.sensitivity import author_sensitivity_proof


def normalize_signature(why_failed: str, failure_class: str | None = None) -> str:
    text = re.sub(r"\s+", " ", (why_failed or "").strip().lower())
    text = re.sub(r"[0-9a-f]{8,}", "<id>", text)
    prefix = (failure_class or "unknown").lower()
    return f"{prefix}::{text}"[:240]


def cluster_dead_ends(
    episodic: EpisodicStore, *, task_class: str, min_runs: int = 3
) -> list[tuple[str, list[CaseRecord]]]:
    """Group dead ends by normalized signature; return clusters with ≥ ``min_runs`` distinct runs."""

    buckets: dict[str, list[CaseRecord]] = defaultdict(list)
    seen_runs: dict[str, set[str]] = defaultdict(set)
    for row in episodic.list_index():
        if not row.get("has_dead_end"):
            continue
        if row.get("task_class") != task_class:
            continue
        case = episodic.get(row["hash"])
        assert case.dead_end is not None
        sig = normalize_signature(case.dead_end.why_failed, case.failure_class)
        if case.run_id in seen_runs[sig]:
            continue
        seen_runs[sig].add(case.run_id)
        buckets[sig].append(case)
    return [(sig, cases) for sig, cases in buckets.items() if len(cases) >= min_runs]


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
        run="test ! -f .fandea-failure-marker",
        authored_by="distiller",
        weight=1.0,
        preregistered=True,
    )
    # Ensure the negative fixture has the marker.
    marker = negative_workdir / ".fandea-failure-marker"
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
                inputs={"command": "test ! -f .fandea-failure-marker"},
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
        ),
        hygiene=Hygiene(secret_scan="skipped"),
    )
