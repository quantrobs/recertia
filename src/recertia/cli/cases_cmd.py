"""CLI: show episodic cases."""

from __future__ import annotations

import json
from pathlib import Path

import typer

cases_app = typer.Typer(help="Episodic cases (read-only).")


def register_cases_commands(app: typer.Typer) -> None:
    app.add_typer(cases_app, name="cases")


@cases_app.command("show")
def cases_show(
    case_id: str = typer.Argument(...),
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    tenant: str = typer.Option("default", "--tenant"),
) -> None:
    """Print one case record by case_id."""

    from recertia.memory.episodic import EpisodicStore

    store = EpisodicStore(runs_root / "runs" / tenant / "episodic")
    rec = store.get_by_case_id(case_id)
    if rec is None:
        typer.echo("case not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(rec.model_dump(mode="json"), indent=2))
