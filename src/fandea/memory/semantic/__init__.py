"""Filesystem fact store with contradiction retention (specs §13.2)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from contracts.fact import Fact


class FactStore:
    """Canonical JSON-in-git layout: ``facts/<scope>/<slug>.json`` plus a review queue file."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.root / "_contradiction_queue.jsonl"
        self._lock = threading.Lock()

    def path_for(self, fact: Fact) -> Path:
        return self.root / fact.scope / f"{fact.slug}.json"

    def write(self, fact: Fact) -> Fact:
        """Persist ``fact``; on contradiction with an existing assertion, retain both and demote."""

        dest = self.path_for(fact)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if dest.exists():
                existing = Fact.model_validate_json(dest.read_text(encoding="utf-8"))
                if existing.assertion != fact.assertion:
                    return self._record_contradiction(existing, fact)
            dest.write_text(fact.model_dump_json(indent=2) + "\n", encoding="utf-8")
            return fact

    def get(self, scope: str, slug: str) -> Fact:
        return Fact.model_validate_json(
            (self.root / scope / f"{slug}.json").read_text(encoding="utf-8")
        )

    def list_facts(self, *, scope: str | None = None) -> list[Fact]:
        facts: list[Fact] = []
        root = self.root / scope if scope else self.root
        if not root.exists():
            return facts
        for path in sorted(root.rglob("*.json")):
            if path.name.startswith("_"):
                continue
            facts.append(Fact.model_validate_json(path.read_text(encoding="utf-8")))
        return facts

    def retrieve(self, query: str, *, scope: str = "project", limit: int = 10) -> list[Fact]:
        q = query.lower()
        scored: list[tuple[float, Fact]] = []
        for fact in self.list_facts(scope=scope):
            if fact.status in ("contradicted", "demoted"):
                trust = 0.1
            elif fact.status == "verified":
                trust = 0.9
            else:
                trust = fact.confidence
            hay = f"{fact.assertion} {fact.slug}".lower()
            score = trust * (1.0 if q in hay else 0.2)
            if any(tok in hay for tok in q.split() if len(tok) > 2):
                score += 0.3
            scored.append((score, fact))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:limit]]

    def _record_contradiction(self, existing: Fact, incoming: Fact) -> Fact:
        now = datetime.now(timezone.utc)
        demoted_existing = existing.model_copy(
            update={
                "status": "contradicted",
                "confidence": min(existing.confidence, 0.2),
                "contradicts": sorted(set(existing.contradicts + [incoming.fact_id])),
            }
        )
        demoted_incoming = incoming.model_copy(
            update={
                "status": "contradicted",
                "confidence": min(incoming.confidence, 0.2),
                "contradicts": sorted(set(incoming.contradicts + [existing.fact_id])),
            }
        )
        # Retain both: keep original path for existing; write incoming under slug__conflict__id.
        self.path_for(demoted_existing).write_text(
            demoted_existing.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        alt = demoted_incoming.model_copy(
            update={"slug": f"{incoming.slug}-conflict-{incoming.fact_id}"[:64].strip("-")}
        )
        alt_path = self.path_for(alt)
        alt_path.write_text(alt.model_dump_json(indent=2) + "\n", encoding="utf-8")
        with self.queue_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "at": now.isoformat(),
                        "existing": demoted_existing.fact_id,
                        "incoming": alt.fact_id,
                        "scope": incoming.scope,
                    }
                )
                + "\n"
            )
        return alt
