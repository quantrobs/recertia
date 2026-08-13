"""CLI: list semantic facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

facts_app = typer.Typer(help="Semantic-plane facts (read-only).")


def register_facts_commands(app: typer.Typer) -> None:
    app.add_typer(facts_app, name="facts")


@facts_app.command("list")
def facts_list(
    scope: Optional[str] = typer.Option(None, "--scope", help="run|project|org|global"),
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    tenant: str = typer.Option("default", "--tenant"),
    facts_root: Optional[Path] = typer.Option(None, "--facts-root"),
) -> None:
    """List facts, optionally filtered by scope."""

    from recertia.memory.semantic import FactStore

    root = facts_root if facts_root is not None else runs_root / "runs" / tenant / "facts"
    store = FactStore(root)
    items = store.list_facts(scope=scope)
    typer.echo(json.dumps({"items": [f.model_dump(mode="json") for f in items]}, indent=2))
