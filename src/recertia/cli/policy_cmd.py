"""CLI: show loaded T2 policy (no secrets)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer


def register_policy_commands(app: typer.Typer) -> None:
    app.command("policy")(policy_show)


def policy_show(
    path: Optional[Path] = typer.Option(None, "--path", help="Policy JSON; default env/file."),
) -> None:
    """Print the loaded Policy document (remaining-work RW-SUR)."""

    import json

    from recertia.policy_load import load_policy

    policy = load_policy(path)
    typer.echo(json.dumps(policy.model_dump(mode="json"), indent=2))
