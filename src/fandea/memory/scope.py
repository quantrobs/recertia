"""Cross-scope promotion with mandatory review + redaction (architecture §15.4)."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.fact import Fact
from contracts.scope import RedactionReport, Scope, ScopePromotion, is_upscope
from fandea.ledger import HashChainLedger
from fandea.memory.semantic import FactStore


class ScopeError(Exception):
    pass


_SECRETISH = ("password", "secret", "token", "api_key", "private")


def redact_assertion(assertion: str) -> tuple[str, RedactionReport]:
    """Strip obvious secret-bearing fragments before upscoping."""

    report = RedactionReport()
    rewritten = assertion
    lowered = assertion.lower()
    for token in _SECRETISH:
        if token in lowered:
            rewritten = "[redacted]"
            report.fields_rewritten["assertion"] = rewritten
            report.notes.append(f"redacted assertion containing {token!r}")
            break
    return rewritten, report


def promote_fact_scope(
    store: FactStore,
    fact: Fact,
    *,
    to_scope: Scope,
    reviewer: str,
    ledger: HashChainLedger | None = None,
) -> tuple[Fact, ScopePromotion]:
    """Promote a fact to a broader scope only with a non-empty reviewer + redaction."""

    if not reviewer.strip():
        raise ScopeError("cross-scope promotion requires a recorded reviewer")
    if not is_upscope(fact.scope, to_scope):
        raise ScopeError(f"refusing non-upscope {fact.scope} → {to_scope}")
    new_assertion, report = redact_assertion(fact.assertion)
    if fact.scope == "run" and to_scope in ("org", "global") and not report.notes:
        report.notes.append("upscope past project; assertion reviewed")
    promoted = fact.model_copy(
        update={
            "scope": to_scope,
            "assertion": new_assertion,
        }
    )
    old_path = store.path_for(fact)
    store.write(promoted)
    new_path = store.path_for(promoted)
    if old_path != new_path and old_path.exists():
        old_path.unlink()
    record = ScopePromotion(
        artifact_kind="fact",
        artifact_id=fact.fact_id,
        from_scope=fact.scope,
        to_scope=to_scope,
        reviewer=reviewer,
        redaction=report,
        promoted_at=datetime.now(timezone.utc),
        ledger_target=f"fact:{fact.fact_id}",
    )
    if ledger is not None:
        ledger.append(
            actor=reviewer,
            action="policy_change",
            target=f"fact:{fact.fact_id}",
            evidence={
                "kind": "scope_promotion",
                "from": fact.scope,
                "to": to_scope,
                "redaction": report.model_dump(mode="json"),
            },
            at=record.promoted_at,
        )
    return promoted, record
