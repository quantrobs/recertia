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

    lift = causal_lift(
        first_attempt_success_sample(treatment),
        first_attempt_success_sample(control),
        task_class=task_class or "unknown",
        snapshot_id=snapshot_id,
        model_version=model_version,
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
