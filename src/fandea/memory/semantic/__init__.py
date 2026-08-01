"""Filesystem fact store with contradiction retention (specs §13.2)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from contracts.fact import Fact


class FactStore:
    """Canonical JSON-in-git layout: ``facts/<scope>/<slug>.json`` plus a review queue file.

    Parsed facts are cached and reused across ``retrieve`` calls (the retrieval hot path);
    the cache is invalidated by any write through this store, or when the tree's
    ``(file count, total size, max mtime_ns)`` stat key changes underneath us.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.root / "_contradiction_queue.jsonl"
        self._lock = threading.Lock()
        self._facts_cache: list[Fact] | None = None
        self._facts_stat: tuple[int, int, int] | None = None

    def path_for(self, fact: Fact) -> Path:
        return self.root / fact.scope / f"{fact.slug}.json"

    def _tree_stat(self) -> tuple[int, int, int]:
        count = 0
        total_size = 0
        max_mtime = 0
        for path in self.root.rglob("*.json"):
            if path.name.startswith("_"):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            count += 1
            total_size += st.st_size
            max_mtime = max(max_mtime, st.st_mtime_ns)
        return (count, total_size, max_mtime)

    def write(self, fact: Fact) -> Fact:
        """Persist ``fact``; on contradiction with an existing assertion, retain both and demote."""

        dest = self.path_for(fact)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._facts_cache = None
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

    def _all_facts_unlocked(self) -> list[Fact]:
        stat = self._tree_stat()
        if self._facts_cache is not None and stat == self._facts_stat:
            return self._facts_cache
        facts: list[Fact] = []
        if self.root.exists():
            for path in sorted(self.root.rglob("*.json")):
                if path.name.startswith("_"):
                    continue
                facts.append(Fact.model_validate_json(path.read_text(encoding="utf-8")))
        self._facts_cache = facts
        self._facts_stat = stat
        return facts

    def list_facts(self, *, scope: str | None = None) -> list[Fact]:
        with self._lock:
            facts = self._all_facts_unlocked()
            if scope is None:
                return list(facts)
            return [f for f in facts if f.scope == scope]

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
