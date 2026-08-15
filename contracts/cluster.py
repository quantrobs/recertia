"""Incremental failure-cluster row (ADR-0015).

Write-time upsert on ``record_dead_end``. Practice and the fail-cluster job read
``eligible`` rows; they MUST NOT rescan episodic blobs to rediscover a cluster.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FailureClusterRow(BaseModel):
    """One ``(task_class, signature)`` bucket, maintained incrementally.

    ``run_ids_sample`` / ``session_ids_sample`` exist only to keep distinct counts
    honest without storing unbounded history. Once a sample hits ``sample_cap`` the
    counters keep incrementing for *new* ids only while they still fit; overflow
    ids still bump the counter (we treat unseen-beyond-sample as new). Rebuild
    from the episodic store if the row is lost.
    """

    model_config = ConfigDict(extra="forbid")

    task_class: str
    signature: str
    n_runs: int = Field(default=0, ge=0)
    n_sessions: int = Field(default=0, ge=0)
    run_ids_sample: list[str] = Field(default_factory=list)
    session_ids_sample: list[str] = Field(default_factory=list)
    last_case_hash: str | None = None
    eligible: bool = False
    updated_at: datetime | None = None
    sample_cap: int = Field(default=32, ge=1, le=256)
    min_runs: int = Field(default=3, ge=1)
    min_sessions: int = Field(default=2, ge=1)

    def note(
        self,
        *,
        run_id: str,
        session_id: str,
        case_hash: str | None,
        at: datetime,
    ) -> "FailureClusterRow":
        """Return an updated row after one dead-end write. O(sample), never a blob scan."""

        runs = list(self.run_ids_sample)
        sessions = list(self.session_ids_sample)
        n_runs = self.n_runs
        n_sessions = self.n_sessions
        if run_id not in runs:
            n_runs += 1
            if len(runs) < self.sample_cap:
                runs.append(run_id)
        if session_id not in sessions:
            n_sessions += 1
            if len(sessions) < self.sample_cap:
                sessions.append(session_id)
        eligible = n_runs >= self.min_runs and n_sessions >= self.min_sessions
        return self.model_copy(
            update={
                "n_runs": n_runs,
                "n_sessions": n_sessions,
                "run_ids_sample": runs,
                "session_ids_sample": sessions,
                "last_case_hash": case_hash if case_hash is not None else self.last_case_hash,
                "eligible": eligible,
                "updated_at": at,
            }
        )
