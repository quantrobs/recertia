"""CLI twins for distill-review (alias of the proposal queue)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

review_app = typer.Typer(help="Distill-review queue (alias of proposals until volume splits).")


def register_review_commands(app: typer.Typer) -> None:
    app.add_typer(review_app, name="review")


@review_app.command("queue")
def review_queue(
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    tenant: str = typer.Option("default", "--tenant"),
    status: str = typer.Option("pending", "--status"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List pending distill-review decisions (proposal alias)."""

    from recertia.proposals.store import ProposalStore

    store = ProposalStore(runs_root / "proposals.sqlite")
    try:
        items = store.list(tenant_id=tenant, status=status, limit=limit)
    finally:
        store.close()
    typer.echo(json.dumps({"alias_of": "proposals", "items": [p.to_dict() for p in items]}, indent=2))


@review_app.command("approve")
def review_approve(
    decision_id: str = typer.Argument(...),
    note: str = typer.Option("", "--note"),
    runs_root: Path = typer.Option(Path(".recertia"), "--runs-root"),
    tenant: str = typer.Option("default", "--tenant"),
    actor: str = typer.Option("cli", "--actor"),
) -> None:
    """Record a human approve on a proposal. Does not write lifecycle=approved."""

    from recertia.ledger import HashChainLedger
    from recertia.proposals.store import ProposalStore

    store = ProposalStore(runs_root / "proposals.sqlite")
    try:
        rec = store.get(decision_id, tenant_id=tenant)
        if rec is None:
            typer.echo("review not found", err=True)
            raise typer.Exit(code=1)
        try:
            updated = store.decide(
                decision_id,
                tenant_id=tenant,
                decision="approve",
                actor=actor,
                note=note,
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    finally:
        store.close()
    ledger = HashChainLedger(runs_root / "runs" / tenant / "ledger.jsonl")
    ledger.append(
        actor=actor,
        action="policy_change",
        target=f"review:{decision_id}",
        evidence={
            "kind": "review_decision",
            "decision": "approve",
            "lifecycle_approved": False,
        },
    )
    typer.echo(json.dumps(updated.to_dict(), indent=2))
