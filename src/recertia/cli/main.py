"""``recertia`` CLI wiring: ``run``, ``runs``, ``ledger``, ``skills``, ``keys``, ``lift``.

Command implementations live in sibling modules; this file builds the Typer app and
re-exports the historical command callables for tests that import them from ``main``.
"""

from __future__ import annotations

import typer

from recertia.cli.keys import keys_issue, keys_list, keys_revoke, register_keys_commands
from recertia.cli.lift import lift_cmd, register_lift_commands
from recertia.cli.runs import (
    ledger_verify,
    register_run_commands,
    resume_cmd,
    run_cmd,
    runs_show,
)
from recertia.cli.skills import (
    register_skills_commands,
    skills_lint,
    skills_promote,
    skills_search,
)

app = typer.Typer(help="Recertia: a self-improving agent system.")
register_run_commands(app)
register_skills_commands(app)
register_keys_commands(app)
register_lift_commands(app)

__all__ = [
    "app",
    "keys_issue",
    "keys_list",
    "keys_revoke",
    "ledger_verify",
    "lift_cmd",
    "resume_cmd",
    "run_cmd",
    "runs_show",
    "skills_lint",
    "skills_promote",
    "skills_search",
]


if __name__ == "__main__":
    app()
