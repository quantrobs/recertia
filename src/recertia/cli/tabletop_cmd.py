"""CLI: incident tabletop walker (does not declare operator GA)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer


def register_tabletop_commands(app: typer.Typer) -> None:
    app.command("tabletop")(tabletop_cmd)


def tabletop_cmd(
    run_id: str = typer.Argument(...),
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    tenant: str = typer.Option("default", "--tenant"),
    restore_from: Optional[Path] = typer.Option(None, "--restore-from", help="Backup archive."),
    restore_dest: Optional[Path] = typer.Option(None, "--restore-dest"),
    follow_up: str = typer.Option("", "--follow-up"),
    output: Optional[Path] = typer.Option(None, "--output", help="Write the tabletop log JSON."),
) -> None:
    """Walk ledger → transcript → failure class; optionally restore a backup."""

    from recertia.ops.tabletop import run_tabletop

    log = run_tabletop(
        run_id,
        runs_root=runs_root,
        tenant=tenant,
        restore_from=restore_from,
        restore_dest=restore_dest,
        follow_up=follow_up,
    )
    text = json.dumps(log, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)
    if log.get("ga_claimed"):
        typer.echo("tabletop must not claim GA", err=True)
        raise typer.Exit(code=2)
    if not log.get("pass"):
        raise typer.Exit(code=1)
