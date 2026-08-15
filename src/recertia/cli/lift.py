"""CLI: report causal_lift for a task class (specs §19)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer


def register_lift_commands(app: typer.Typer) -> None:
    app.command("lift")(lift_cmd)


def lift_cmd(
    task_class: str = typer.Option("repo-chore", "--task-class"),
    eval_db: Path = typer.Option(Path(".recertia/evals.db"), "--eval-db"),
    snapshot_id: Optional[str] = typer.Option(None, "--snapshot-id"),
) -> None:
    """Report causal_lift for a task class (specs §19). Never claims lift when CI includes zero."""

    from contracts.eval import BinomialSample
    from recertia.evals.statistics import causal_lift
    from recertia.evals.store import EvalStore

    store = EvalStore(eval_db)
    try:
        counts = store.arm_counts(task_class=task_class, snapshot_id=snapshot_id)
        treatment = counts.get("treatment", BinomialSample(successes=0, trials=0))
        control = counts.get("control", BinomialSample(successes=0, trials=0))
        result = causal_lift(
            treatment,
            control,
            task_class=task_class,
            snapshot_id=snapshot_id,
        )
    finally:
        store.close()

    typer.echo(f"task_class={task_class}")
    typer.echo(f"treatment={treatment.successes}/{treatment.trials}")
    typer.echo(f"control={control.successes}/{control.trials}")
    if result.estimate is None:
        typer.echo(f"status={result.render_status()}")
    else:
        typer.echo(f"estimate={result.estimate:.4f}")
        if result.interval is not None:
            typer.echo(
                f"interval=[{result.interval.low:.4f}, {result.interval.high:.4f}] "
                f"level={result.interval.level} method={result.interval.method}"
            )
        typer.echo(f"status={result.render_status()}")
    if result.status == "not_established":
        typer.echo("claim=not established (interval includes zero)")
