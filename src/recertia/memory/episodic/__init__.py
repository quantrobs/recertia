"""Episodic memory: immutable, content-addressed case records (specs §13.3, M2).

Written for every attempt. Dead ends are retrieved by ``evolve`` to suppress re-selection
of an approach whose recorded ``why_failed`` still applies.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeadEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approach: str
    why_failed: str
    evidence_ref: str | None = None


class CaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    run_id: str
    attempt_no: int
    task_class: str | None = None
    request_excerpt: str = ""
    outcome: Literal["solved", "failed", "abandoned"]
    failure_class: str | None = None
    dead_end: DeadEnd | None = None
    transcript_ref: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    approach: str | None = None
    skill_id: str | None = None
    skill_version: int | None = None
    distilled_into: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EpisodicStore:
    """Filesystem + JSONL index. Cases are content-addressed under ``cases/<hash>.json``.

    The parsed index is cached in memory: retrieval paths call ``list_index`` on every
    run, and the append-only file only changes through ``write`` here. The cache is
    validated against the file's ``(size, mtime_ns)`` so externally appended rows are
    still picked up with at most one re-parse.

    Episodic history only grows, so the lookups ``retrieve`` performs on every task must not
    scan it. Rows are bucketed by ``(kind, task_class)`` as the cache is built, which turns
    "the 3 most recent dead ends for this task class" from a reverse scan over all history —
    unbounded when the class has no history to short-circuit on — into a slice of a list.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.cases_dir = self.root / "cases"
        self.index_path = self.root / "index.jsonl"
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._index_cache: list[dict] | None = None
        self._index_stat: tuple[int, int] | None = None
        self._buckets: dict[tuple[str, str | None], list[dict]] | None = None

    def _index_file_stat(self) -> tuple[int, int] | None:
        try:
            st = self.index_path.stat()
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime_ns)

    @staticmethod
    def _bucket_keys(row: dict) -> list[tuple[str, str | None]]:
        """Bucket keys a row belongs to: one per kind, times "any class" and its own class."""

        kinds: list[str] = []
        if row.get("has_dead_end"):
            kinds.append("dead_end")
        if row.get("outcome") == "solved":
            kinds.append("solved")
        task_class = row.get("task_class")
        return [(kind, cls) for kind in kinds for cls in (None, task_class)]

    def _index_unlocked(self) -> list[dict]:
        """The cached index rows themselves — callers must not mutate the list."""

        stat = self._index_file_stat()
        if self._index_cache is not None and stat == self._index_stat:
            return self._index_cache
        rows: list[dict] = []
        if self.index_path.exists():
            with self.index_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        self._index_cache = rows
        self._index_stat = stat
        self._buckets = None
        return rows

    def _buckets_unlocked(self) -> dict[tuple[str, str | None], list[dict]]:
        rows = self._index_unlocked()
        if self._buckets is None:
            buckets: dict[tuple[str, str | None], list[dict]] = {}
            for row in rows:
                for key in self._bucket_keys(row):
                    buckets.setdefault(key, []).append(row)
            self._buckets = buckets
        return self._buckets

    def _recent_rows(self, kind: str, task_class: str | None, limit: int) -> list[dict]:
        """Up to ``limit`` rows of ``kind``, most recent first. Falsy class means any."""

        if limit <= 0:
            return []
        with self._lock:
            bucket = self._buckets_unlocked().get((kind, task_class or None), [])
            # Buckets are append-ordered, so the tail is the most recent.
            return bucket[-limit:][::-1]

    def write(self, case: CaseRecord) -> str:
        blob = case.model_dump_json().encode()
        content_hash = hashlib.sha256(blob).hexdigest()
        dest = self.cases_dir / f"{content_hash}.json"
        row = {
            "case_id": case.case_id,
            "hash": content_hash,
            "run_id": case.run_id,
            "attempt_no": case.attempt_no,
            "outcome": case.outcome,
            "failure_class": case.failure_class,
            "task_class": case.task_class,
            "approach": case.approach,
            "has_dead_end": case.dead_end is not None,
        }
        with self._lock:
            if not dest.exists():
                dest.write_bytes(blob)
            with self.index_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            if self._index_cache is not None:
                self._index_cache.append(row)
                self._index_stat = self._index_file_stat()
                if self._buckets is not None:
                    for key in self._bucket_keys(row):
                        self._buckets.setdefault(key, []).append(row)
        return content_hash

    def get(self, content_hash: str) -> CaseRecord:
        return CaseRecord.model_validate_json(
            (self.cases_dir / f"{content_hash}.json").read_text(encoding="utf-8")
        )

    def list_index(self) -> list[dict]:
        """Every index row, oldest first. Copies; prefer the bounded lookups on hot paths."""

        with self._lock:
            return list(self._index_unlocked())

    def dead_ends_for(
        self, *, task_class: str | None = None, limit: int = 3
    ) -> list[CaseRecord]:
        rows = self._recent_rows("dead_end", task_class, limit)
        return [self.get(row["hash"]) for row in rows]

    def solved_case_ids_for(
        self, *, task_class: str | None = None, limit: int = 3
    ) -> list[str]:
        """Case ids of the most recent solved analogues, newest first.

        Returns ids rather than records: ``retrieve`` cites solved cases as references and
        reading each case file back would put ``limit`` file reads on the critical path.
        """

        return [row["case_id"] for row in self._recent_rows("solved", task_class, limit)]

    def cases_for_run(self, run_id: str) -> list[CaseRecord]:
        return [self.get(r["hash"]) for r in self.list_index() if r["run_id"] == run_id]

    def approach_still_applies(self, dead_end: DeadEnd, *, current_approach: str) -> bool:
        """Whether ``evolve`` should suppress ``current_approach`` given this dead end."""

        return dead_end.approach == current_approach
