"""CLI: start/resume runs, inspect route logs, verify the ledger. Goal-aware (Variant B)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from contracts.budget import Budget
from contracts.criteria import TaskCriterion
from contracts.goal import Goal, compile_goal
from contracts.run import Task
from fandea.graph.engine import GraphOrchestrator
from fandea.ledger import HashChainLedger, LedgerVerificationError

runs_app = typer.Typer(help="Inspect runs.")
ledger_app = typer.Typer(help="Verify the provenance ledger.")
goal_app = typer.Typer(help="Goal helpers (Variant B).")


def _load_spec(spec_path: Path) -> dict:
    return json.loads(spec_path.read_text())


def _build_orchestrator(
    runs_root: Path,
    *,
    skills_root: Path,
    index_path: Path,
) -> tuple[GraphOrchestrator, object]:
    """Wire SkillStore + Retriever so ``fandea run`` can apply the skill library."""

    from fandea.memory.procedural.store import SkillStore
    from fandea.retrieval.index import SkillIndex
    from fandea.retrieval.pipeline import Retriever

    store = SkillStore(skills_root)
    index = SkillIndex(index_path)
    index.rebuild(store.iter_loaded())
    retriever = Retriever(index)
    orch = GraphOrchestrator(
        runs_root,
        store=store,
        retriever=retriever,
        # Empty fingerprint: only mismatch when both sides declare a tool (retrieval §preconditions).
        env_fingerprint={},
    )
    return orch, index


def register_run_commands(app: typer.Typer) -> None:
    """Attach ``run`` / ``resume`` to the root app and nest runs/ledger/goal typers."""

    app.add_typer(runs_app, name="runs")
    app.add_typer(ledger_app, name="ledger")
    app.add_typer(goal_app, name="goal")
    app.command("run")(run_cmd)
    app.command("resume")(resume_cmd)


def run_cmd(
    spec: Optional[Path] = typer.Option(
        None, "--spec", exists=True, help="Path to a run spec JSON file (legacy or goal-aware)."
    ),
    goal: Optional[Path] = typer.Option(
        None, "--goal", exists=True, help="Path to a Goal JSON file (Variant B preferred)."
    ),
    runs_root: Path = typer.Option(Path(".fandea"), "--runs-root", help="Where run state is persisted."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Defaults to a fresh UUID."),
    workdir: Optional[Path] = typer.Option(None, "--workdir"),
    skills_root: Path = typer.Option(
        Path("skills"), "--skills-root", help="Procedural skill library root."
    ),
    index: Path = typer.Option(
        Path(".fandea/skill_index.db"),
        "--index",
        help="Skill retrieval index (default: under --runs-root).",
    ),
    ablation: bool = typer.Option(
        False, "--ablation", help="Assign control arm via T3 ablation sampler (outside nodes)."
    ),
) -> None:
    """Start a run and drive it to completion (or to the first unrecoverable stop)."""

    if goal is None and spec is None:
        typer.echo("Provide --goal or --spec", err=True)
        raise typer.Exit(code=2)

    rid = run_id or uuid.uuid4().hex[:12]
    data: dict = {}
    if spec is not None:
        data = _load_spec(spec)

    task_goal: Goal | None = None
    if goal is not None:
        task_goal = Goal.model_validate_json(goal.read_text())
    elif "goal" in data:
        task_goal = Goal.model_validate(data["goal"])

    task_data = data.get("task", {})
    request = task_data.get("request") or data.get("request")
    if task_goal is not None and task_goal.context and not request:
        request = task_goal.context

    task = Task(
        task_id=task_data.get("task_id", rid),
        goal=task_goal,
        request=request,
        task_class=task_data.get("task_class")
        or (task_goal.task_class if task_goal else None)
        or data.get("task_class"),
        submitted_at=datetime.now(timezone.utc),
        is_eval_fixture=bool(task_data.get("is_eval_fixture", False)),
    )
    criteria = [TaskCriterion(**c) for c in data.get("criteria", [])]
    if not criteria and task_goal is not None:
        criteria = compile_goal(task_goal)
    budget = Budget(**data["budget"]) if "budget" in data else Budget()
    script = data.get("script")
    wd = workdir or (Path(data["workdir"]) if "workdir" in data else runs_root / "workspaces" / rid)
    wd.mkdir(parents=True, exist_ok=True)

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

    index_path = index
    if index == Path(".fandea/skill_index.db"):
        index_path = runs_root / "skill_index.db"

    orchestrator, skill_index = _build_orchestrator(
        runs_root, skills_root=skills_root, index_path=index_path
    )
    try:
        state = orchestrator.start(
            rid, task, criteria, budget=budget, workdir=wd, script=script, arm=arm
        )
    finally:
        orchestrator.close()
        skill_index.close()

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
                reason = entry.reason.replace("\u2192", "->")
                typer.echo(f"  [{entry.attempt_no}] {entry.node} --{entry.route}--> {reason}")
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


@goal_app.command("compile")
def goal_compile(
    goal_path: Path = typer.Argument(..., exists=True, help="Goal JSON file"),
) -> None:
    """Compile a Goal to TaskCriterion[] and print JSON."""
    goal = Goal.model_validate_json(goal_path.read_text())
    criteria = compile_goal(goal)
    typer.echo(json.dumps([c.model_dump(mode="json") for c in criteria], indent=2))
