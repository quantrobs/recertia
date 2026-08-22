"""CLI: ``recertia faithfulness`` — eval-only condensed-memory interventions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

faithfulness_app = typer.Typer(help="Faithfulness interventions (eval-only, never production).")


def register_faithfulness_commands(app: typer.Typer) -> None:
    app.add_typer(faithfulness_app, name="faithfulness")


@faithfulness_app.command("run")
def faithfulness_run(
    skill_id: str = typer.Option(..., "--skill-id"),
    version: int = typer.Option(1, "--version"),
    task_class: str = typer.Option("repo-chore", "--task-class"),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    interventions: str = typer.Option(
        "empty,corrupt,irrelevant,filler", "--interventions"
    ),
    donor_skill_id: Optional[str] = typer.Option(None, "--donor-skill-id"),
    donor_version: int = typer.Option(1, "--donor-version"),
    eval_db: Path = typer.Option(Path(".recertia/evals.db"), "--eval-db"),
    ledger_path: Optional[Path] = typer.Option(None, "--ledger"),
    trials: int = typer.Option(0, "--trials", help="Reserved; transformers always run."),
) -> None:
    """Materialise interventions in memory, score stored tagged trials, write a ledger tag."""

    del trials
    import json

    from contracts.eval import BinomialSample
    from recertia.evals.faithfulness import evaluate_faithfulness, strategy_tag
    from recertia.evals.interventions import apply_intervention
    from recertia.evals.store import EvalStore
    from recertia.memory.procedural.store import SkillStore
    from recertia.policy_load import load_policy

    policy = load_policy()
    names = [part.strip() for part in interventions.split(",") if part.strip()]
    store = SkillStore(skills_root)
    skill = store.get_version(skill_id, version)
    donor = None
    if "irrelevant" in names:
        if not donor_skill_id:
            raise typer.BadParameter("--donor-skill-id required for irrelevant")
        donor = store.get_version(donor_skill_id, donor_version)

    transformed = {}
    for name in names:
        transformed[name] = apply_intervention(skill, name, donor=donor)  # type: ignore[arg-type]

    eval_store = EvalStore(eval_db)
    try:
        observations = eval_store.list_observations(task_class=task_class)
    finally:
        eval_store.close()

    baseline_rows = [
        obs
        for obs in observations
        if obs.skill_id == skill_id
        and obs.skill_version == version
        and not (obs.strategy or "").startswith("faithfulness:")
        and not obs.is_eval_fixture
    ]
    baseline = BinomialSample(
        successes=sum(1 for obs in baseline_rows if obs.first_attempt_success),
        trials=len(baseline_rows),
    )
    outcomes = {}
    events: dict[str, list[str]] = {}
    for name in names:
        tag = strategy_tag(name)  # type: ignore[arg-type]
        rows = [obs for obs in observations if obs.strategy == tag]
        outcomes[name] = BinomialSample(
            successes=sum(1 for obs in rows if obs.first_attempt_success),
            trials=len(rows),
        )
        events[name] = [obs.terminal or "unknown" for obs in rows]

    report = evaluate_faithfulness(
        skill=skill,
        baseline=baseline,
        baseline_events=[obs.terminal or "unknown" for obs in baseline_rows],
        outcomes=outcomes,  # type: ignore[arg-type]
        events=events,  # type: ignore[arg-type]
        donor=donor,
        skill_used=bool(baseline_rows),
        min_independent_runs=policy.min_independent_runs,
    )
    payload = report.model_dump(mode="json")
    payload["transformed"] = {
        name: {"title": body.title, "step_intents": [s.intent for s in body.steps]}
        for name, body in transformed.items()
    }
    typer.echo(json.dumps(payload, indent=2, default=str))

    if ledger_path is not None:
        from recertia.ledger import HashChainLedger

        ledger = HashChainLedger(ledger_path)
        ledger.append(
            actor="recertia-faithfulness",
            action="faithfulness_report",
            target=f"{skill_id}@v{version}",
            evidence={
                "score": report.score,
                "interventions": names,
                "tagged": True,
                "production_path": False,
            },
            at=datetime.now(timezone.utc),
        )
