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
    """Filesystem + JSONL index. Cases are content-addressed under ``cases/<hash>.json``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.cases_dir = self.root / "cases"
        self.index_path = self.root / "index.jsonl"
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, case: CaseRecord) -> str:
        blob = case.model_dump_json().encode()
        content_hash = hashlib.sha256(blob).hexdigest()
        dest = self.cases_dir / f"{content_hash}.json"
        with self._lock:
            if not dest.exists():
                dest.write_bytes(blob)
            with self.index_path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
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
                    )
                    + "\n"
                )
        return content_hash

    def get(self, content_hash: str) -> CaseRecord:
        return CaseRecord.model_validate_json(
            (self.cases_dir / f"{content_hash}.json").read_text(encoding="utf-8")
        )

    def list_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        rows: list[dict] = []
        with self.index_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def dead_ends_for(
        self, *, task_class: str | None = None, limit: int = 3
    ) -> list[CaseRecord]:
        out: list[CaseRecord] = []
        for row in reversed(self.list_index()):
            if not row.get("has_dead_end"):
                continue
            if task_class and row.get("task_class") != task_class:
                continue
            out.append(self.get(row["hash"]))
            if len(out) >= limit:
                break
        return out

    def cases_for_run(self, run_id: str) -> list[CaseRecord]:
        return [self.get(r["hash"]) for r in self.list_index() if r["run_id"] == run_id]

    def approach_still_applies(self, dead_end: DeadEnd, *, current_approach: str) -> bool:
        """Whether ``evolve`` should suppress ``current_approach`` given this dead end."""

        return dead_end.approach == current_approach
