"""CLI: run improvement-plane jobs (mine / curate / practice / recertify)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

jobs_app = typer.Typer(help="Improvement-plane jobs (proposals only; never write approved).")


def register_jobs_commands(app: typer.Typer) -> None:
    app.add_typer(jobs_app, name="jobs")


@jobs_app.command("run")
def jobs_run(
    job: str = typer.Argument(
        ..., help="Job name: mine | curator | practice | recertify | shadow"
    ),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print proposals; do not persist."),
    max_proposals: int = typer.Option(10, "--max-proposals"),
    hint: Optional[list[str]] = typer.Option(
        None, "--hint", help="Mine job: human-artifact hint (repeatable)."
    ),
    one_off: Optional[list[str]] = typer.Option(
        None, "--one-off", help="Practice job: one-off cluster reason (repeatable)."
    ),
    tool_upgraded: Optional[str] = typer.Option(
        None, "--tool-upgraded", help="Recertify job: tool name that upgraded."
    ),
    submit: bool = typer.Option(
        False, "--submit", help="Persist mined drafts as candidates (mine only)."
    ),
) -> None:
    """Run an offline improvement job under a proposal budget."""

    from recertia.jobs import JobBudget, JobRunner
    from recertia.jobs.workers import (
        curator_active_set_and_dedup,
        enqueue_mined_candidate,
        mine_from_repo_hints,
        practice_from_one_offs,
        recertify_stale,
        schedule_shadow_evaluations,
    )
    from recertia.memory.procedural.store import SkillStore

    store = SkillStore(skills_root)
    runner = JobRunner(store, runs_root=runs_root / "jobs")
    budget = JobBudget(max_proposals=max_proposals)
    name = job.strip().lower()

    if name in {"mine", "miner"}:
        hints = list(hint or ["README.md chore hints"])
        result = runner.run("mine", lambda: mine_from_repo_hints(store, hints=hints), budget=budget)
        if submit and not dry_run:
            for proposal in result.proposals:
                draft = enqueue_mined_candidate(store, proposal)
                typer.echo(f"candidate {draft.skill_id}@v{draft.version}")
    elif name in {"curator", "curate"}:
        result = runner.run(
            "curator", lambda: curator_active_set_and_dedup(store), budget=budget
        )
    elif name == "practice":
        reasons = list(one_off or ["unsolved one-off cluster"])
        curriculum = None if dry_run else runs_root / "practice-curriculum"
        result = runner.run(
            "practice",
            lambda: practice_from_one_offs(reasons, curriculum_dir=curriculum),
            budget=budget,
        )
    elif name == "recertify":
        result = runner.run(
            "recertify",
            lambda: recertify_stale(store, tool_upgraded=tool_upgraded),
            budget=budget,
        )
    elif name == "shadow":
        result = runner.run(
            "shadow",
            lambda: schedule_shadow_evaluations(store),
            budget=budget,
        )
    else:
        typer.echo(
            f"unknown job {job!r}; expected mine|curator|practice|recertify|shadow",
            err=True,
        )
        raise typer.Exit(code=2)

    payload = {
        "job": result.job,
        "proposals": [
            {
                "kind": p.kind,
                "skill_id": p.skill_id,
                "version": p.version,
                "rationale": p.rationale,
                "payload": p.payload,
            }
            for p in result.proposals
        ],
        "dry_run": dry_run,
    }
    typer.echo(json.dumps(payload, indent=2))
