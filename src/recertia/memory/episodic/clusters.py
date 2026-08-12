"""Incremental failure-cluster index. Updated on dead-end write; never a blob scan."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from contracts.cluster import FailureClusterRow


def normalize_signature(why_failed: str, failure_class: str | None = None) -> str:
    text = re.sub(r"\s+", " ", (why_failed or "").strip().lower())
    text = re.sub(r"[0-9a-f]{8,}", "<id>", text)
    prefix = (failure_class or "unknown").lower()
    return f"{prefix}::{text}"[:240]


class ClusterStore:
    """JSON map of ``task_class::signature`` → ``FailureClusterRow``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._rows: dict[str, FailureClusterRow] | None = None

    @staticmethod
    def key(task_class: str, signature: str) -> str:
        return f"{task_class}::{signature}"

    def _load(self) -> dict[str, FailureClusterRow]:
        if self._rows is not None:
            return self._rows
        rows: dict[str, FailureClusterRow] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for key, payload in raw.items():
                rows[key] = FailureClusterRow.model_validate(payload)
        self._rows = rows
        return rows

    def _flush(self) -> None:
        assert self._rows is not None
        payload = {key: row.model_dump(mode="json") for key, row in self._rows.items()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def upsert(
        self,
        *,
        task_class: str,
        signature: str,
        run_id: str,
        session_id: str,
        case_hash: str | None,
        min_runs: int = 3,
        min_sessions: int = 2,
        at: datetime | None = None,
    ) -> FailureClusterRow:
        when = at or datetime.now(timezone.utc)
        with self._lock:
            rows = self._load()
            key = self.key(task_class, signature)
            current = rows.get(key) or FailureClusterRow(
                task_class=task_class,
                signature=signature,
                min_runs=min_runs,
                min_sessions=min_sessions,
            )
            updated = current.note(
                run_id=run_id, session_id=session_id, case_hash=case_hash, at=when
            )
            rows[key] = updated
            self._flush()
            return updated

    def eligible(self, *, task_class: str | None = None) -> list[FailureClusterRow]:
        with self._lock:
            rows = self._load()
        out = [row for row in rows.values() if row.eligible]
        if task_class is not None:
            out = [row for row in out if row.task_class == task_class]
        return out

    def get(self, task_class: str, signature: str) -> FailureClusterRow | None:
        with self._lock:
            return self._load().get(self.key(task_class, signature))
