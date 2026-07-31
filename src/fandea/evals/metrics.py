"""Aggregate §11 and §23 metrics from run-shaped observation dicts (M4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from contracts.eval import BinomialSample, MetricReport
from contracts.skill import SkillVersion
from fandea.evals.fake_edges import fake_edge_checks as derive_fake_edge_checks
from fandea.evals.statistics import brier_score, causal_lift, mean, rate


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
) -> MetricReport:
    unavailable: dict[str, str] = {}
    # User-facing metrics and lift exclude fixtures and synthetic practice
    # traffic before arms are formed; filtering afterwards contaminates CIs.
    non_eval = [
        r
        for r in rows
        if not r.get("is_eval_fixture") and r.get("arm") != "practice"
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

    return MetricReport(
        snapshot_id=snapshot_id,
        model_version=model_version,
        task_class=task_class,
        reuse_rate=reuse,
        first_attempt_success=fas.rate,
        attempts_to_success=attempts,
        cost_per_solved_task=cost_per,
        causal_lift=lift,
        calibration_error=calibration,
        abstention_precision=abst_prec,
        merge_gap_rate=merge_gap,
        parallel_speedup=speedup,
        fake_edge_rate=fake,
        judge_isolation_violations=judge_isolation_violations,
        unavailable=unavailable,
        at=datetime.now(timezone.utc),
    )
