"""``fandea`` CLI (M0): ``run``, ``runs show --route-log``, ``ledger verify``.

A run is specified as a small JSON file (see ``docs/implementation-plan.md`` M0 for what a
run needs at this milestone — no memory, no model, just a task, locked criteria, and a
scripted attempt):

```json
{
  "task": {"request": "bump the pinned dependency", "task_class": "repo-chore"},
  "criteria": [
    {"id": "tests", "kind": "command", "run": "pytest -q", "source": "caller", "weight": 1.0}
  ],
  "script": ["python3 -m pip --version"],
  "budget": {"max_attempts": 4},
  "workdir": "/path/to/scratch/repo"
}
```
"""

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

app = typer.Typer(help="Fandea: a self-improving agent system.")
runs_app = typer.Typer(help="Inspect runs.")
ledger_app = typer.Typer(help="Verify the provenance ledger.")
skills_app = typer.Typer(help="Lint and search the skill library.")
app.add_typer(runs_app, name="runs")
app.add_typer(ledger_app, name="ledger")
app.add_typer(skills_app, name="skills")


def _load_spec(spec_path: Path) -> dict:
    return json.loads(spec_path.read_text())


@app.command("lift")
def lift_cmd(
    task_class: str = typer.Option("repo-chore", "--task-class"),
    eval_db: Path = typer.Option(Path(".fandea/evals.db"), "--eval-db"),
    snapshot_id: Optional[str] = typer.Option(None, "--snapshot-id"),
) -> None:
    """Report causal_lift for a task class (specs §19). Never claims lift when CI includes zero."""

    from contracts.eval import BinomialSample
    from fandea.evals.statistics import causal_lift
    from fandea.evals.store import EvalStore

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


@app.command("run")
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


@app.command("resume")
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


@skills_app.command("lint")
def skills_lint(
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
) -> None:
    """Structural + semantic lint of every skill version under ``skills_root``."""

    from fandea.memory.procedural.lint import lint_store
    from fandea.memory.procedural.store import SkillStore

    store = SkillStore(skills_root)
    report = lint_store(store)
    failures = {k: v for k, v in report.items() if v}
    for key, violations in report.items():
        if violations:
            typer.echo(f"FAIL {key}")
            for v in violations:
                typer.echo(f"  - {v}")
        else:
            typer.echo(f"OK   {key}")
    if failures:
        raise typer.Exit(code=1)


@skills_app.command("search")
def skills_search(
    query: str = typer.Argument(...),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    index_path: Path = typer.Option(Path(".fandea/skill_index.db"), "--index"),
    workdir: Path = typer.Option(Path("."), "--workdir"),
    explain: bool = typer.Option(False, "--explain", help="Print scores and drop reasons."),
    env: Optional[str] = typer.Option(
        None, "--env", help="JSON object of tool→version for fingerprint matching."
    ),
) -> None:
    """Retrieval debug endpoint (specs §9): scores and drop reasons without running a task."""

    from fandea.memory.procedural.store import SkillStore
    from fandea.retrieval.index import SkillIndex
    from fandea.retrieval.pipeline import Retriever

    store = SkillStore(skills_root)
    index = SkillIndex(index_path)
    try:
        index.rebuild(store.iter_loaded())
        retriever = Retriever(index)
        env_fp = json.loads(env) if env else {}
        bundle, explanation = retriever.search(
            query, workdir=workdir, env_fingerprint=env_fp
        )
    finally:
        index.close()

    if explain:
        typer.echo(f"snapshot={explanation.snapshot_id}")
        typer.echo(f"lexical_hits={len(explanation.lexical_hits)} vector_hits={len(explanation.vector_hits)}")
        for d in explanation.dropped:
            typer.echo(f"  DROP {d.skill_id}@v{d.version} stage={d.stage} reason={d.reason}")
        for sid, ver, score, reason in explanation.demoted:
            typer.echo(f"  DEMOTE {sid}@v{ver} score={score:.3f} ({reason})")
    for c in bundle.skills:
        typer.echo(f"{c.skill_id}@v{c.version} score={c.score}")
    if not bundle.skills:
        typer.echo("(empty bundle)")


if __name__ == "__main__":
    app()
