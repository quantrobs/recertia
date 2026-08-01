"""CLI: emit MetricReport / weekly lift summary for operator cadence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer


def register_metrics_commands(app: typer.Typer) -> None:
    app.command("metrics")(metrics_cmd)


def metrics_cmd(
    task_class: str = typer.Option("repo-chore", "--task-class"),
    eval_db: Path = typer.Option(Path(".recertia/evals.db"), "--eval-db"),
    snapshot_id: Optional[str] = typer.Option(None, "--snapshot-id"),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    canary_root: Path = typer.Option(
        Path("evals/canary/planted-failure"), "--canary-root"
    ),
    model_version: Optional[str] = typer.Option(None, "--model-version"),
    output: Optional[Path] = typer.Option(None, "--output", help="Write JSON report."),
) -> None:
    """Build a MetricReport from the eval store (honest unavailable reasons when sparse)."""

    from recertia.evals.canary import run_judge_canary
    from recertia.evals.metrics import build_metric_report
    from recertia.evals.store import EvalStore
    from recertia.memory.procedural.active_set import recompute_active_set
    from recertia.memory.procedural.composition import mean_composition_depth
    from recertia.memory.procedural.store import SkillStore
    from recertia.review.autonomy_config import DEFAULT_AUTONOMY

    store = EvalStore(eval_db)
    try:
        rows = store.metric_rows(task_class=task_class, snapshot_id=snapshot_id)
        snap = snapshot_id or (rows[0]["snapshot_id"] if rows else "none")
        skill_store = SkillStore(skills_root)
        _updated, pressure = recompute_active_set(skill_store, config=DEFAULT_AUTONOMY)
        mean_pressure = sum(pressure.values()) / len(pressure) if pressure else 0.0
        canary = run_judge_canary(root=canary_root, model_version=model_version)
        ever_benched = sum(
            1
            for _v, status, _s in skill_store.iter_loaded()
            if status.retirement.benched_at is not None or status.lifecycle == "benched"
        )
        restored = sum(
            1
            for _v, status, _s in skill_store.iter_loaded()
            if status.retirement.restored_at is not None
        )
        report = build_metric_report(
            rows,
            snapshot_id=snap,
            task_class=task_class,
            model_version=model_version,
            active_cap_pressure=mean_pressure,
            judge_false_pass_rate=canary.false_pass_rate,
            mean_composition_depth=mean_composition_depth(skill_store),
            retirement_benched=ever_benched if ever_benched else None,
            retirement_restored=restored if ever_benched else None,
        )
    finally:
        store.close()

    payload = report.model_dump(mode="json")
    text = json.dumps(payload, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)
    if report.causal_lift is not None and report.causal_lift.status == "not_established":
        typer.echo("claim=not established (interval includes zero)", err=True)
