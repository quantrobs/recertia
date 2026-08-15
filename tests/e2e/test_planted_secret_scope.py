"""Phase-4: planted-secret must not cross tenant/scope retrieval boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.fact import Fact, FactProvenance
from recertia.memory.scope import promote_fact_scope, redact_assertion, tenant_readable
from recertia.memory.semantic import FactStore


def test_planted_secret_redacted_on_upscope_and_isolated_by_tenant_readable(
    tmp_path: Path,
) -> None:
    store = FactStore(tmp_path / "facts")
    secret_fact = Fact(
        fact_id="secret-1",
        slug="secret-1",
        assertion="api_token=planted-secret-value-do-not-leak",
        scope="run",
        provenance=FactProvenance(asserting_run="run-a"),
        authored_at=datetime.now(timezone.utc),
    )
    store.write(secret_fact)

    # Same-tenant narrow scope may hold the secret; upscope must redact.
    rewritten, report = redact_assertion(secret_fact.assertion)
    assert rewritten == "[redacted]"
    assert report.fields_rewritten

    promoted, record = promote_fact_scope(
        store, secret_fact, to_scope="org", reviewer="alice"
    )
    assert promoted.assertion == "[redacted]"
    assert record.redaction.fields_rewritten

    # Tenant B readable set cannot see org-scoped artifacts it was not granted.
    assert tenant_readable(promoted.scope, {"org", "global"})
    assert not tenant_readable(promoted.scope, {"run", "project"})

    # Retrieval under a foreign readable set must not surface the planted secret text.
    hits = store.retrieve("planted-secret", scope="org", limit=10)
    for hit in hits:
        assert "planted-secret-value" not in hit.assertion
