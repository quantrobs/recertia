"""Persistent eval observations and per-task-class control baselines (M4)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from contracts.eval import BinomialSample, ControlBaseline, EvalObservation


class EvalStore:
    """SQLite store keyed by snapshot so baselines survive across library versions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def close(self) -> None:
        self._conn.close()

    def _init(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    run_id TEXT PRIMARY KEY,
                    task_class TEXT NOT NULL,
                    arm TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    model_version TEXT,
                    first_attempt_success INTEGER NOT NULL,
                    predicted_success REAL,
                    terminal TEXT,
                    fixture_id TEXT,
                    is_eval_fixture INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_class TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    model_version TEXT,
                    successes INTEGER NOT NULL,
                    trials INTEGER NOT NULL,
                    interval_json TEXT,
                    created_at TEXT NOT NULL,
                    report_id TEXT,
                    UNIQUE(task_class, snapshot_id, report_id)
                );
                CREATE INDEX IF NOT EXISTS idx_obs_snap ON observations(snapshot_id, task_class);
                CREATE INDEX IF NOT EXISTS idx_base_class ON baselines(task_class, created_at);
                """
            )

    def record_observation(self, obs: EvalObservation) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO observations (
                    run_id, task_class, arm, snapshot_id, model_version,
                    first_attempt_success, predicted_success, terminal, fixture_id,
                    is_eval_fixture, recorded_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.run_id,
                    obs.task_class,
                    obs.arm,
                    obs.snapshot_id,
                    obs.model_version,
                    int(obs.first_attempt_success),
                    obs.predicted_success,
                    obs.terminal,
                    obs.fixture_id,
                    int(obs.is_eval_fixture),
                    obs.recorded_at.isoformat(),
                    obs.model_dump_json(),
                ),
            )

    def write_baseline(self, baseline: ControlBaseline) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO baselines (
                    task_class, snapshot_id, model_version, successes, trials,
                    interval_json, created_at, report_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline.task_class,
                    baseline.snapshot_id,
                    baseline.model_version,
                    baseline.control.successes,
                    baseline.control.trials,
                    baseline.interval.model_dump_json() if baseline.interval else None,
                    baseline.created_at.isoformat(),
                    baseline.report_id,
                ),
            )

    def baselines_for(self, task_class: str) -> list[ControlBaseline]:
        rows = self._conn.execute(
            """
            SELECT * FROM baselines
            WHERE task_class = ?
            ORDER BY created_at ASC, id ASC
            """,
            (task_class,),
        ).fetchall()
        return [self._row_to_baseline(r) for r in rows]

    def latest_baseline(self, task_class: str) -> ControlBaseline | None:
        rows = self.baselines_for(task_class)
        return rows[-1] if rows else None

    def arm_counts(
        self, *, task_class: str, snapshot_id: str | None = None
    ) -> dict[str, BinomialSample]:
        sql = """
            SELECT arm,
                   SUM(first_attempt_success) AS successes,
                   COUNT(*) AS trials
            FROM observations
            WHERE task_class = ? AND is_eval_fixture = 0
        """
        params: list[object] = [task_class]
        if snapshot_id is not None:
            sql += " AND snapshot_id = ?"
            params.append(snapshot_id)
        sql += " GROUP BY arm"
        out: dict[str, BinomialSample] = {}
        for row in self._conn.execute(sql, params):
            out[row["arm"]] = BinomialSample(
                successes=int(row["successes"] or 0), trials=int(row["trials"] or 0)
            )
        return out

    def list_observations(
        self, *, task_class: str | None = None, snapshot_id: str | None = None
    ) -> list[EvalObservation]:
        clauses: list[str] = []
        params: list[object] = []
        if task_class is not None:
            clauses.append("task_class = ?")
            params.append(task_class)
        if snapshot_id is not None:
            clauses.append("snapshot_id = ?")
            params.append(snapshot_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT payload FROM observations{where} ORDER BY recorded_at ASC", params
        ).fetchall()
        return [EvalObservation.model_validate_json(r["payload"]) for r in rows]

    @staticmethod
    def _row_to_baseline(row: sqlite3.Row) -> ControlBaseline:
        from contracts.eval import ConfidenceInterval

        interval = None
        if row["interval_json"]:
            interval = ConfidenceInterval.model_validate_json(row["interval_json"])
        return ControlBaseline(
            task_class=row["task_class"],
            snapshot_id=row["snapshot_id"],
            model_version=row["model_version"],
            control=BinomialSample(successes=row["successes"], trials=row["trials"]),
            interval=interval,
            created_at=datetime.fromisoformat(row["created_at"]),
            report_id=row["report_id"],
        )


def baseline_from_control(
    *,
    task_class: str,
    snapshot_id: str,
    control: BinomialSample,
    model_version: str | None = None,
    report_id: str | None = None,
) -> ControlBaseline:
    from fandea.evals.statistics import wilson_interval

    return ControlBaseline(
        task_class=task_class,
        snapshot_id=snapshot_id,
        model_version=model_version,
        control=control,
        interval=wilson_interval(control.successes, control.trials),
        created_at=datetime.now(timezone.utc),
        report_id=report_id,
    )
