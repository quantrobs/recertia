"""Backlog hardening: sandbox approvals, scope promotion, telemetry, migrations, R3 CI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.fact import Fact, FactProvenance
from fandea.governance.sandbox import DEFAULT_SANDBOX, ApprovalGate, SandboxPolicy
from fandea.ledger import HashChainLedger
from fandea.memory.scope import ScopeError, promote_fact_scope
from fandea.memory.semantic import FactStore
from fandea.solver.sandbox import SandboxError, SandboxLimits, run_sandboxed
from fandea.solver.tools import ApprovalRequiredError, ToolRuntime, default_registry
from fandea.store import (
    apply_sqlite_migrations,
    postgres_migration_sql,
    verify_sqlite_schema,
)
from fandea.telemetry import REQUIRED_EVENTS, reset_telemetry


def test_non_read_tools_require_approval(tmp_path: Path) -> None:
    work = tmp_path / "w"
    work.mkdir()
    runtime = ToolRuntime(default_registry(), require_approval_for_non_read=True)
    with pytest.raises(ApprovalRequiredError, match="requires approval"):
        runtime.invoke("shell", {"command": "true"}, workdir=work, step_id="s1")
    # read tools never need approval
    (work / "f.txt").write_text("hi")
    ok = runtime.invoke("read_file", {"path": "f.txt"}, workdir=work, step_id="s2")
    assert ok.ok
    gate = ApprovalGate()
    gate.approve("shell", actor="alice")
    runtime.approval_gate = gate
    approved = runtime.invoke("shell", {"command": "true"}, workdir=work, step_id="s3")
    assert not approved.ok
    assert approved.exit_code == 126


def test_host_subprocess_sandbox_is_disabled(tmp_path: Path) -> None:
    work = tmp_path / "jail"
    work.mkdir()
    (work / "marker").write_text("in-jail")
    with pytest.raises(SandboxError, match="disabled"):
        run_sandboxed("cat marker", workdir=work, limits=SandboxLimits())
    assert DEFAULT_SANDBOX.backend == "container"
    assert isinstance(SandboxPolicy(), SandboxPolicy)


def test_scope_promotion_requires_reviewer_and_redacts(tmp_path: Path) -> None:
    store = FactStore(tmp_path / "facts")
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    fact = Fact(
        fact_id="api-token-note",
        scope="project",
        slug="api-token-note",
        assertion="The service password is hunter2 for staging.",
        provenance=FactProvenance(asserting_human="bob"),
        authored_at=datetime.now(timezone.utc),
    )
    store.write(fact)
    with pytest.raises(ScopeError, match="reviewer"):
        promote_fact_scope(store, fact, to_scope="org", reviewer="")
    promoted, record = promote_fact_scope(
        store, fact, to_scope="org", reviewer="alice", ledger=ledger
    )
    assert promoted.scope == "org"
    assert promoted.assertion == "[redacted]"
    assert record.redaction.fields_rewritten
    assert store.get("org", "api-token-note").scope == "org"
    assert not (tmp_path / "facts" / "project" / "api-token-note.json").exists()
    assert ledger.entries()[-1].action == "policy_change"


def test_telemetry_required_events_surface() -> None:
    tel = reset_telemetry(admin_actor="test-admin", tenant_id="test")
    with tel.span("run", tenant_id="test", run_id="r1"):
        for name in sorted(REQUIRED_EVENTS):
            tel.emit(name, tenant_id="test", run_id="r1")
    assert tel.missing_required() == []
    assert any(s.name == "run" for s in tel.spans)


def test_sqlite_migration_snapshot_and_postgres_dialect(tmp_path: Path) -> None:
    db = tmp_path / "snapshot.sqlite"
    applied = apply_sqlite_migrations(db)
    assert "001_init" in applied
    tables = verify_sqlite_schema(db)
    assert {"skills_meta", "facts_meta", "embeddings", "run_checkpoints", "schema_migrations"} <= tables
    # Idempotent
    assert apply_sqlite_migrations(db) == []
    pg = postgres_migration_sql()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in pg
    assert "embedding vector" in pg
