"""HEX / compress enablement predicates (remaining-work RW-HEX / RW-6)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from contracts.eval import MetricReport
from contracts.policy import Policy

if TYPE_CHECKING:
    from recertia.jobs import JobRunner


def hex_compress_skip_reason(
    policy: Policy | None,
    report: MetricReport | None,
    *,
    job: str,
    recovery: bool = False,
) -> str | None:
    """Return a skip reason, or ``None`` if HEX/compress may emit proposals.

    Flipping policy flags is not enough: ``practice_conversion`` must be numeric and
    ``causal_lift`` must be established-positive unless ``recovery`` is set (ledger-noted
    experiment after ``a1`` refuted).
    """

    flags = policy.improvement if policy is not None else None
    if job in {"practice_hex", "hex"}:
        if flags is None or not flags.practice_hex_search:
            return "practice_hex_search disabled"
    elif job == "compress":
        if flags is None or not flags.curator_compress:
            return "curator_compress disabled"
    else:
        return None

    if report is None or report.practice_conversion is None:
        return "practice_conversion unavailable"
    if recovery:
        return None
    lift = report.causal_lift
    if lift is None or lift.status != "established_positive":
        return "causal_lift not established positive"
    return None


def attach_enablement(
    runner: JobRunner,
    *,
    eval_db: Path | str,
    skills_root: Path | str,
    task_class: str = "repo-chore",
) -> None:
    """Load the latest MetricReport so HEX/compress predicates see real holes."""

    from recertia.evals.report import assemble_metric_report
    from recertia.evals.store import EvalStore
    from recertia.memory.procedural.store import SkillStore

    store = EvalStore(eval_db)
    try:
        runner.enablement_report = assemble_metric_report(
            store,
            skill_store=SkillStore(skills_root),
            task_class=task_class,
        )
    finally:
        store.close()
