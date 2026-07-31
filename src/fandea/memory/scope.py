"""Cross-scope promotion with mandatory review + redaction (architecture §15.4)."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.fact import Fact
from contracts.scope import RedactionReport, Scope, ScopePromotion, is_upscope
from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus
from fandea.ledger import HashChainLedger
from fandea.memory.procedural.allocate import allocate_and_write
from fandea.memory.procedural.store import SkillStore
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


def redact_skill_text(text: str) -> tuple[str, RedactionReport]:
    return redact_assertion(text)


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


def promote_skill_scope(
    store: SkillStore,
    version: SkillVersion,
    *,
    to_scope: Scope,
    reviewer: str,
    ledger: HashChainLedger | None = None,
) -> tuple[SkillVersion, ScopePromotion]:
    """Promote a skill by writing version N+1 at the broader scope (immutable versions)."""

    if not reviewer.strip():
        raise ScopeError("cross-scope promotion requires a recorded reviewer")
    if not is_upscope(version.scope, to_scope):
        raise ScopeError(f"refusing non-upscope {version.scope} → {to_scope}")
    new_intent, report = redact_skill_text(version.intent)
    draft = version.model_copy(update={"scope": to_scope, "intent": new_intent, "version": 1})
    stamped = allocate_and_write(store, draft)
    store.write_status(
        SkillStatus(
            skill_id=stamped.skill_id,
            version=stamped.version,
            lifecycle="candidate",
            active=False,
        )
    )
    store.write_stats(SkillStats(skill_id=stamped.skill_id, version=stamped.version))
    record = ScopePromotion(
        artifact_kind="skill",
        artifact_id=f"{stamped.skill_id}@v{stamped.version}",
        from_scope=version.scope,
        to_scope=to_scope,
        reviewer=reviewer,
        redaction=report,
        promoted_at=datetime.now(timezone.utc),
        ledger_target=f"skill:{stamped.skill_id}@v{stamped.version}",
    )
    if ledger is not None:
        ledger.append(
            actor=reviewer,
            action="policy_change",
            target=record.ledger_target or stamped.skill_id,
            evidence={
                "kind": "scope_promotion",
                "from": version.scope,
                "to": to_scope,
                "redaction": report.model_dump(mode="json"),
            },
            at=record.promoted_at,
        )
    return stamped, record


def tenant_readable(artifact_scope: Scope, readable_scopes: set[str]) -> bool:
    """Multi-tenant isolation: artifact visible only if its scope is in the caller's set."""

    return artifact_scope in readable_scopes
