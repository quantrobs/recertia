"""Filesystem fact store with contradiction retention (specs §13.2)."""

from __future__ import annotations

import heapq
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from contracts.fact import Fact

DEFAULT_REVALIDATE_INTERVAL_S = 1.0
"""How long a cached fact tree may be trusted without a full per-file stat sweep.

Cache validation used to cost one stat per fact on every ``retrieve`` — at 1600 facts, 81% of
the call. Validation is now tiered by what each class of change is detectable with:

* writes through this store invalidate the cache directly;
* an external file added or removed changes its directory's mtime, so the per-call gate
  stats only the known directories (O(scopes), independent of fact count);
* an external *in-place* edit of an existing fact changes neither, and is caught by the full
  stat sweep, which runs at most this often.

Only the last case is delayed, and only for out-of-process edits.
"""

DIR_MTIME_AMBIGUITY_NS = 20_000_000
"""Window in which a directory mtime cannot prove "unchanged".

Linux stamps inode times from a coarse clock (4ms granularity on a HZ=250 kernel, 10ms at
HZ=100), so a file added in the same tick as our last sweep leaves the directory mtime we
recorded. When the recorded mtime is that close to the sweep, equality proves nothing and the
gate falls through to a full sweep. Sized above the coarsest common tick.
"""


class _ScoringRow:
    """Precomputed per-fact scoring inputs, built once per cache epoch.

    ``retrieve`` runs on every task, and re-deriving trust and a lowercased haystack per
    call allocated a copy of every fact's text on every call. Holding them costs one
    lowercase copy of ``assertion + slug`` per cached fact — the same bytes the old code
    allocated transiently, now amortised instead of re-created.
    """

    __slots__ = ("fact", "trust", "haystack")

    def __init__(self, fact: Fact) -> None:
        self.fact = fact
        if fact.status in ("contradicted", "demoted"):
            self.trust = 0.1
        elif fact.status == "verified":
            self.trust = 0.9
        else:
            self.trust = fact.confidence
        self.haystack = f"{fact.assertion} {fact.slug}".lower()


class FactStore:
    """Canonical JSON-in-git layout: ``facts/<scope>/<slug>.json`` plus a review queue file.

    Parsed facts are cached and reused across ``retrieve`` calls (the retrieval hot path);
    the cache is invalidated by any write through this store, and revalidated against the
    tree's ``(file count, total size, max mtime_ns)`` stat key at most once per
    ``revalidate_interval_s``.
    """

    def __init__(self, root: Path | str, *, revalidate_interval_s: float | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.root / "_contradiction_queue.jsonl"
        self._lock = threading.Lock()
        self._facts_cache: list[Fact] | None = None
        self._facts_stat: tuple[int, int, int] | None = None
        self._rows_cache: dict[str | None, list[_ScoringRow]] = {}
        self._fact_dirs: list[str] = []
        self._dir_key: tuple[tuple[str, int], ...] | None = None
        self._checked_at: float | None = None
        self._swept_at_ns: int = 0
        self.revalidate_interval_s = (
            DEFAULT_REVALIDATE_INTERVAL_S
            if revalidate_interval_s is None
            else revalidate_interval_s
        )

    def path_for(self, fact: Fact) -> Path:
        return self.root / fact.scope / f"{fact.slug}.json"

    def _tree_stat(self) -> tuple[int, int, int]:
        """``(file count, total size, max mtime_ns)`` over the fact tree.

        Also records the directories holding facts, which the per-call gate stats. Uses
        ``os.scandir``, which carries stat data on the entry: ``pathlib.rglob`` spent more
        time constructing ``Path`` objects than the stat syscalls themselves cost.
        """

        count = 0
        total_size = 0
        max_mtime = 0
        dirs: list[str] = [str(self.root)]
        pending = [str(self.root)]
        while pending:
            try:
                entries = list(os.scandir(pending.pop()))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(entry.path)
                        pending.append(entry.path)
                        continue
                    name = entry.name
                    if name.startswith("_") or not name.endswith(".json"):
                        continue
                    st = entry.stat()
                except OSError:
                    continue
                count += 1
                total_size += st.st_size
                if st.st_mtime_ns > max_mtime:
                    max_mtime = st.st_mtime_ns
        self._fact_dirs = dirs
        return (count, total_size, max_mtime)

    def _current_dir_key(self) -> tuple[tuple[str, int], ...]:
        """Cheap gate: ``(dir, mtime_ns)`` for each known fact directory.

        A file appearing or disappearing bumps its directory's mtime, and a new scope
        directory bumps the root's, so this catches every add/remove for the cost of one
        stat per directory — no per-fact syscalls.
        """

        key: list[tuple[str, int]] = []
        for path in self._fact_dirs or [str(self.root)]:
            try:
                key.append((path, os.stat(path).st_mtime_ns))
            except OSError:
                key.append((path, -1))
        return tuple(key)

    def _invalidate_unlocked(self) -> None:
        self._facts_cache = None
        self._rows_cache = {}
        self._dir_key = None
        self._checked_at = None

    def write(self, fact: Fact) -> Fact:
        """Persist ``fact``; on contradiction with an existing assertion, retain both and demote."""

        dest = self.path_for(fact)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._invalidate_unlocked()
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
        if self._facts_cache is not None and not self._sweep_needed_unlocked():
            return self._facts_cache
        stat = self._tree_stat()
        self._checked_at = time.monotonic()
        self._swept_at_ns = time.time_ns()
        self._dir_key = self._current_dir_key()
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
        self._rows_cache = {}
        return facts

    def _sweep_needed_unlocked(self) -> bool:
        """Whether the cheap gate or the elapsed interval calls for a full stat sweep."""

        if self._checked_at is None or self._dir_key is None:
            return True
        if self._current_dir_key() != self._dir_key:
            return True
        floor = self._swept_at_ns - DIR_MTIME_AMBIGUITY_NS
        if any(mtime >= floor for _path, mtime in self._dir_key):
            return True
        return (time.monotonic() - self._checked_at) >= self.revalidate_interval_s

    def _scoring_rows_unlocked(self, scope: str | None) -> list[_ScoringRow]:
        facts = self._all_facts_unlocked()
        rows = self._rows_cache.get(scope)
        if rows is None:
            rows = [
                _ScoringRow(f) for f in facts if scope is None or f.scope == scope
            ]
            self._rows_cache[scope] = rows
        return rows

    def list_facts(self, *, scope: str | None = None) -> list[Fact]:
        with self._lock:
            facts = self._all_facts_unlocked()
            if scope is None:
                return list(facts)
            return [f for f in facts if f.scope == scope]

    def retrieve(self, query: str, *, scope: str = "project", limit: int = 10) -> list[Fact]:
        """Top-``limit`` facts for ``query``, best first.

        Scoring is unchanged: every fact scores at least ``trust * 0.2``, so this is a scan
        by construction. What it no longer does per call is re-derive trust, re-lowercase
        every fact, copy the fact list, or sort the whole library to take ten rows.
        """

        q = query.lower()
        tokens = [tok for tok in q.split() if len(tok) > 2]
        with self._lock:
            rows = self._scoring_rows_unlocked(scope)
        # (-score, position) ordered heap == a stable sort by descending score, so ties keep
        # library order exactly as the previous full sort did.
        ranked: list[tuple[float, int, Fact]] = []
        for pos, row in enumerate(rows):
            hay = row.haystack
            trust = row.trust
            score = trust if q in hay else trust * 0.2
            for tok in tokens:
                if tok in hay:
                    score += 0.3
                    break
            ranked.append((-score, pos, row.fact))
        return [fact for _, _, fact in heapq.nsmallest(limit, ranked)]

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
