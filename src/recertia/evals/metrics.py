"""Aggregate §11 and §23 metrics from run-shaped observation dicts (M4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from contracts.eval import BinomialSample, MetricReport
from contracts.skill import SkillVersion
from recertia.evals.fake_edges import fake_edge_checks as derive_fake_edge_checks
from recertia.evals.statistics import brier_score, causal_lift, mean, rate

_HUMANISH = frozenset({"human_authored", "mined_from_human_artifact"})


def first_attempt_success_sample(rows: Sequence[dict[str, Any]]) -> BinomialSample:
    """``first_attempt_success``: reached distill with attempt_no==1 (specs §11)."""

    trials = len(rows)
    successes = sum(1 for r in rows if r.get("first_attempt_success"))
    return BinomialSample(successes=successes, trials=trials)


def _arm_rate_series(rows: Sequence[dict[str, Any]]) -> list[float]:
    """Per-snapshot rates when ≥2 snapshots exist, else the Bernoulli 0/1 vector."""

    snaps: dict[str, list[int]] = {}
    bernoulli: list[float] = []
    for row in rows:
        success = 1 if row.get("first_attempt_success") else 0
        bernoulli.append(float(success))
        snap = str(row.get("snapshot_id") or "")
        pair = snaps.setdefault(snap, [0, 0])
        pair[0] += success
        pair[1] += 1
    if len(snaps) >= 2:
        return [succ / trials for succ, trials in snaps.values() if trials]
    return bernoulli


def build_metric_report(
    rows: Sequence[dict[str, Any]],
    *,
    snapshot_id: str,
    task_class: str | None = None,
    model_version: str | None = None,
    merge_audits: Sequence[dict[str, Any]] | None = None,
    step_waves: Sequence[dict[str, Any]] | None = None,
    fake_edge_checks: Sequence[bool] | None = None,
    skill: SkillVersion | None = None,
    transcripts: Sequence[dict[str, Any]] | None = None,
    judge_isolation_violations: int = 0,
    retirement_benched: int | None = None,
    retirement_restored: int | None = None,
    active_cap_pressure: float | None = None,
    judge_false_pass_rate: float | None = None,
    mean_composition_depth: float | None = None,
    regression_rate: float | None = None,
    approved_applied: int | None = None,
    approved_total: int | None = None,
    precision_at_3: float | None = None,
    prior_precision_at_3: float | None = None,
    skills_added: int | None = None,
    min_independent_runs: int = 5,
) -> MetricReport:
    unavailable: dict[str, str] = {}
    # User-facing metrics and lift exclude fixtures and synthetic practice
    # traffic before arms are formed; filtering afterwards contaminates CIs.
    non_eval = [
        r
        for r in rows
        if not r.get("is_eval_fixture")
        and r.get("arm") != "practice"
        and r.get("arm") != "shadow"
        and not str(r.get("strategy") or "").startswith("faithfulness:")
    ]
    treatment = [r for r in non_eval if r.get("arm", "treatment") == "treatment"]
    control = [r for r in non_eval if r.get("arm") == "control"]

    fas = first_attempt_success_sample(non_eval)
    reuse_num = sum(1 for r in non_eval if r.get("strategy") in ("apply", "adapt"))
    reuse = rate(reuse_num, len(non_eval))

    solved_attempts = [
        float(r["attempt_no"])
        for r in non_eval
        if r.get("terminal") == "solved" and r.get("attempt_no") is not None
    ]
    attempts = mean(solved_attempts)

    costs = [float(r["cost_usd"]) for r in non_eval if r.get("terminal") == "solved" and "cost_usd" in r]
    solved = sum(1 for r in non_eval if r.get("terminal") == "solved")
    cost_per = (sum(costs) / solved) if solved and costs else None
    if solved and not costs:
        unavailable["cost_per_solved_task"] = "no cost fields on observations"

    preds = [float(r["predicted_success"]) for r in non_eval if r.get("predicted_success") is not None]
    outs = [
        bool(r.get("first_attempt_success"))
        for r in non_eval
        if r.get("predicted_success") is not None
    ]
    calibration = brier_score(preds, outs) if preds else None
    if calibration is None:
        unavailable["calibration_error"] = "no predicted_success observations"

    abstentions = [r for r in non_eval if r.get("terminal") == "abstained"]
    good_abstain = sum(1 for r in abstentions if r.get("abstention_confirmed"))
    abst_prec = rate(good_abstain, len(abstentions))
    if not abstentions:
        unavailable["abstention_precision"] = "no abstentions in window"

    t_rates = _arm_rate_series(treatment)
    c_rates = _arm_rate_series(control)
    lift = causal_lift(
        first_attempt_success_sample(treatment),
        first_attempt_success_sample(control),
        task_class=task_class or "unknown",
        snapshot_id=snapshot_id,
        model_version=model_version,
        min_independent_runs=min_independent_runs,
        treatment_rates=t_rates or None,
        control_rates=c_rates or None,
    )

    merge_gap = None
    if merge_audits is not None:
        if not merge_audits:
            merge_gap = 0.0
        else:
            gaps = sum(1 for a in merge_audits if a.get("missing"))
            merge_gap = gaps / len(merge_audits)
    else:
        unavailable["merge_gap_rate"] = "no merge audits supplied"

    speedup = None
    if step_waves is not None:
        ratios = []
        for w in step_waves:
            wall = w.get("duration_s")
            serial = w.get("serial_duration_s")
            if wall and serial and wall > 0:
                ratios.append(float(serial) / float(wall))
        speedup = mean(ratios)
        if speedup is not None and merge_gap is None:
            # Specs §23: never report speedup alone.
            unavailable["parallel_speedup"] = "refused without merge_gap_rate"
            speedup = None
    else:
        unavailable["parallel_speedup"] = "no step_waves supplied"

    fake = None
    checks = list(fake_edge_checks) if fake_edge_checks is not None else None
    if checks is None and skill is not None and transcripts is not None:
        checks = []
        for transcript in transcripts:
            checks.extend(derive_fake_edge_checks(skill, transcript))
    if checks is not None:
        if not checks:
            fake = 0.0
        else:
            fake = sum(1 for ok in checks if not ok) / len(checks)
    else:
        unavailable["fake_edge_rate"] = "no fake edge observations supplied"

    curation_gap = _curation_gap(non_eval, unavailable)
    practice_conversion = _practice_conversion(rows, unavailable)
    retirement = _retirement_reversal(
        retirement_benched, retirement_restored, unavailable
    )
    pressure = active_cap_pressure
    if pressure is None:
        unavailable["active_cap_pressure"] = "no active_cap_pressure supplied"
    false_pass = judge_false_pass_rate
    if false_pass is None:
        unavailable["judge_false_pass_rate"] = "no canary observations supplied"
    composition = mean_composition_depth
    if composition is None:
        unavailable["mean_composition_depth"] = "no composition depth supplied"
    if regression_rate is None:
        unavailable["regression_rate"] = "no golden regression window supplied"

    library_yield = _library_yield(approved_applied, approved_total, unavailable)
    retrieval_precision = precision_at_3
    if retrieval_precision is None:
        unavailable["retrieval_precision_at_3"] = "probe set empty or retrieve not run"
    retrieval_decay = _retrieval_decay(
        precision_at_3, prior_precision_at_3, skills_added, unavailable
    )

    return MetricReport(
        snapshot_id=snapshot_id,
        model_version=model_version,
        task_class=task_class,
        reuse_rate=reuse,
        first_attempt_success=fas.rate,
        attempts_to_success=attempts,
        cost_per_solved_task=cost_per,
        regression_rate=regression_rate,
        causal_lift=lift,
        calibration_error=calibration,
        abstention_precision=abst_prec,
        merge_gap_rate=merge_gap,
        parallel_speedup=speedup,
        fake_edge_rate=fake,
        judge_isolation_violations=judge_isolation_violations,
        curation_gap=curation_gap,
        practice_conversion=practice_conversion,
        retirement_reversal_rate=retirement,
        active_cap_pressure=pressure,
        judge_false_pass_rate=false_pass,
        mean_composition_depth=composition,
        library_yield=library_yield,
        retrieval_precision_at_3=retrieval_precision,
        retrieval_decay=retrieval_decay,
        unavailable=unavailable,
        at=datetime.now(timezone.utc),
    )


def _curation_gap(rows: Sequence[dict[str, Any]], unavailable: dict[str, str]) -> float | None:
    labelled = [r for r in rows if r.get("curation")]
    if not labelled:
        unavailable["curation_gap"] = "no curation provenance on observations"
        return None
    human = [r for r in labelled if r.get("curation") in _HUMANISH]
    distilled = [r for r in labelled if r.get("curation") == "self_distilled"]
    if not human or not distilled:
        unavailable["curation_gap"] = "need both humanish and self_distilled observations"
        return None
    human_rate = first_attempt_success_sample(human).rate
    distilled_rate = first_attempt_success_sample(distilled).rate
    if human_rate is None or distilled_rate is None:
        unavailable["curation_gap"] = "empty curation cohorts"
        return None
    return human_rate - distilled_rate


def _practice_conversion(
    rows: Sequence[dict[str, Any]], unavailable: dict[str, str]
) -> float | None:
    practice = [r for r in rows if r.get("arm") == "practice"]
    if not practice:
        unavailable["practice_conversion"] = "no practice-arm observations"
        return None
    converted = sum(1 for r in practice if r.get("practice_converted"))
    return converted / len(practice)


def _retirement_reversal(
    benched: int | None, restored: int | None, unavailable: dict[str, str]
) -> float | None:
    if benched is None or restored is None:
        unavailable["retirement_reversal_rate"] = "no retirement bench/restore counts supplied"
        return None
    if benched <= 0:
        unavailable["retirement_reversal_rate"] = "no benched versions in window"
        return None
    return restored / benched


def _library_yield(
    applied: int | None, total: int | None, unavailable: dict[str, str]
) -> float | None:
    if total is None or total <= 0:
        unavailable["library_yield"] = "no approved skills"
        return None
    if applied is None:
        unavailable["library_yield"] = "application events not recorded"
        return None
    return applied / total


def _retrieval_decay(
    precision: float | None,
    prior: float | None,
    skills_added: int | None,
    unavailable: dict[str, str],
) -> float | None:
    if precision is None or prior is None:
        unavailable["retrieval_decay"] = "fewer than two probe snapshots"
        return None
    if skills_added is None or skills_added <= 0:
        unavailable["retrieval_decay"] = "skill-count denominator zero"
        return None
    return (precision - prior) * (100.0 / float(skills_added))


def library_yield_inputs(
    rows: Sequence[dict[str, Any]], *, approved_ids: set[str]
) -> tuple[int | None, int]:
    """Return ``(approved_applied | None, approved_total)`` for :func:`build_metric_report`.

    ``approved_applied`` is ``None`` when the window has no application events (skill ids
    on non-eval rows), so yield stays unavailable instead of a silent zero.
    """

    total = len(approved_ids)
    if total <= 0:
        return None, 0
    app_rows = [
        r
        for r in rows
        if not r.get("is_eval_fixture")
        and r.get("arm") not in {"practice", "shadow"}
        and r.get("skill_id")
        and r.get("strategy") in {"apply", "adapt"}
    ]
    if not app_rows and not any(
        r.get("skill_id")
        for r in rows
        if not r.get("is_eval_fixture") and r.get("arm") not in {"practice", "shadow"}
    ):
        return None, total
    used = {str(r["skill_id"]) for r in app_rows if r.get("skill_id") in approved_ids}
    return len(used), total
