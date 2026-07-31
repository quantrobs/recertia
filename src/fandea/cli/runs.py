"""CLI: start/resume runs, inspect route logs, verify the ledger."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from contracts.budget import Budget
from contracts.criteria import TaskCriterion
from contracts.run import Task
from fandea.graph.engine import GraphOrchestrator
from fandea.ledger import HashChainLedger, LedgerVerificationError

runs_app = typer.Typer(help="Inspect runs.")
ledger_app = typer.Typer(help="Verify the provenance ledger.")


def _load_spec(spec_path: Path) -> dict:
    return json.loads(spec_path.read_text())


def register_run_commands(app: typer.Typer) -> None:
    """Attach ``run`` / ``resume`` to the root app and nest runs/ledger typers."""

    app.add_typer(runs_app, name="runs")
    app.add_typer(ledger_app, name="ledger")
    app.command("run")(run_cmd)
    app.command("resume")(resume_cmd)


def run_cmd(
    spec: Path = typer.Option(..., "--spec", exists=True, help="Path to a run spec JSON file."),
    runs_root: Path = typer.Option(Path(".fandea"), "--runs-root", help="Where run state is persisted."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Defaults to a fresh UUID."),
    ablation: bool = typer.Option(
        False, "--ablation", help="Assign control arm via T3 ablation sampler (outside nodes)."
    ),
) -> None:
    """Start a run and drive it to completion (or to the first unrecoverable stop)."""

    data = _load_spec(spec)
    rid = run_id or uuid.uuid4().hex[:12]

    task_data = data.get("task", {})
    task = Task(
        task_id=task_data.get("task_id", rid),
        request=task_data["request"],
        task_class=task_data.get("task_class"),
        submitted_at=datetime.now(timezone.utc),
        is_eval_fixture=bool(task_data.get("is_eval_fixture", False)),
    )
    criteria = [TaskCriterion(**c) for c in data.get("criteria", [])]
    budget = Budget(**data["budget"]) if "budget" in data else Budget()
    script = data.get("script")
    workdir = Path(data["workdir"]) if "workdir" in data else runs_root / "workspaces" / rid
    workdir.mkdir(parents=True, exist_ok=True)

    arm = data.get("arm", "treatment")
    if ablation:
        from fandea.evals.ablation import assign_arm

        decision = assign_arm(
            run_id=rid,
            task_class=task.task_class,
            is_eval_fixture=task.is_eval_fixture,
            has_external_effects=bool(task_data.get("has_external_effects", False)),
            explicit_skill_supplied=bool(task_data.get("explicit_skill")),
        )
        arm = decision.arm
        typer.echo(f"ablation arm={arm} ({decision.reason})")

    orchestrator = GraphOrchestrator(runs_root)
    try:
        state = orchestrator.start(
            rid, task, criteria, budget=budget, workdir=workdir, script=script, arm=arm
        )
    finally:
        orchestrator.close()

    typer.echo(f"run_id={rid} terminal={state.terminal} arm={state.arm}")
    if state.failure is not None:
        typer.echo(f"failure_class={state.failure.failure_class}")
    raise typer.Exit(code=0 if state.terminal in ("solved", "abstained") else 1)


def resume_cmd(
    run_id: str = typer.Argument(...),
    runs_root: Path = typer.Option(Path(".fandea"), "--runs-root"),
    spec: Optional[Path] = typer.Option(
        None, "--spec", help="Re-supply script/workdir if not resuming in place."
    ),
) -> None:
    """Resume a run from its last checkpoint. Safe to call after a killed process."""

    workdir = runs_root / "workspaces" / run_id
    script = None
    if spec is not None:
        data = _load_spec(spec)
        script = data.get("script")
        if "workdir" in data:
            workdir = Path(data["workdir"])

    orchestrator = GraphOrchestrator(runs_root)
    try:
        state = orchestrator.resume(run_id, workdir=workdir, script=script)
    finally:
        orchestrator.close()

    typer.echo(f"run_id={run_id} terminal={state.terminal}")
    raise typer.Exit(code=0 if state.terminal in ("solved", "abstained") else 1)


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(...),
    runs_root: Path = typer.Option(Path(".fandea"), "--runs-root"),
    route_log: bool = typer.Option(False, "--route-log", help="Print the full route log."),
) -> None:
    orchestrator = GraphOrchestrator(runs_root)
    try:
        latest = orchestrator.checkpoints.latest(run_id)
        if latest is None:
            typer.echo(f"no such run: {run_id}", err=True)
            raise typer.Exit(code=1)
        _, _, next_node, state = latest
        typer.echo(
            f"run_id={run_id} terminal={state.terminal} next_node={next_node} "
            f"attempt_no={state.attempt_no}"
        )
        if route_log:
            for entry in state.route_log:
                typer.echo(f"  [{entry.attempt_no}] {entry.node} --{entry.route}--> {entry.reason}")
    finally:
        orchestrator.close()


@ledger_app.command("verify")
def ledger_verify(
    runs_root: Path = typer.Option(Path(".fandea"), "--runs-root"),
) -> None:
    ledger = HashChainLedger(runs_root / "ledger.jsonl")
    try:
        ledger.verify()
    except LedgerVerificationError as exc:
        typer.echo(f"LEDGER INVALID: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"ledger OK: {len(ledger.entries())} entries verified")
