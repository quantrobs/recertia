"""CLI: federated memory query (remaining-work RW-SUR)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

memory_app = typer.Typer(help="Federated retrieve debug (does not start a run).")


def register_memory_commands(app: typer.Typer) -> None:
    app.add_typer(memory_app, name="memory")


@memory_app.command("query")
def memory_query(
    query: str = typer.Argument(...),
    skills_root: Path = typer.Option(Path("skills"), "--skills-root"),
    facts_root: Path = typer.Option(Path("facts"), "--facts-root"),
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    index_path: Path = typer.Option(Path(".recertia/skill_index.db"), "--index"),
    workdir: Path = typer.Option(Path("."), "--workdir"),
    env: Optional[str] = typer.Option(None, "--env", help="JSON object of tool→version."),
    limit: int = typer.Option(8, "--limit"),
) -> None:
    """Print scores and drop reasons across skills, facts, and cases."""

    from recertia.memory.query import federated_query

    env_fp = json.loads(env) if env else {}
    payload = federated_query(
        query,
        skills_root=skills_root,
        facts_root=facts_root,
        episodic_root=runs_root / "episodic",
        index_path=index_path,
        workdir=workdir,
        env_fingerprint=env_fp,
        limit=limit,
        affordance_path=runs_root / "affordances.json",
    )
    typer.echo(json.dumps(payload, indent=2))
