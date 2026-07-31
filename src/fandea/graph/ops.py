"""Stable operation ids and at-least-once execution (M0; refactor-plan B6).

Every side-effecting call a node makes — a tool invocation, a ledger append — is keyed by
``(run_id, attempt_no, node, op_seq)``. Before performing the side effect, the caller checks
whether that key already has a recorded result; if so, it returns the stored result instead
of repeating the effect. This is what makes "kill the process mid-run and resume" safe: a
resumed run re-enters a node from its last checkpoint and may re-call the same operations, but
each one either no-ops (already applied) or runs exactly once (not yet applied) — never twice.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


class OperationLedger:
    """SQLite-backed idempotency store, one row per applied operation."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                run_id TEXT NOT NULL,
                attempt_no INTEGER NOT NULL,
                node TEXT NOT NULL,
                op_seq INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                PRIMARY KEY (run_id, attempt_no, node, op_seq)
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, run_id: str, attempt_no: int, node: str, op_seq: int) -> tuple[bool, object]:
        """Returns ``(already_applied, result)``. ``result`` is ``None`` when not applied."""

        with self._lock:
            row = self._conn.execute(
                "SELECT result_json FROM operations WHERE run_id=? AND attempt_no=? AND node=? AND op_seq=?",
                (run_id, attempt_no, node, op_seq),
            ).fetchone()
        if row is None:
            return False, None
        return True, json.loads(row[0])

    def put(self, run_id: str, attempt_no: int, node: str, op_seq: int, result: object) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO operations (run_id, attempt_no, node, op_seq, result_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, attempt_no, node, op_seq, json.dumps(result)),
            )
            self._conn.commit()

    def run_once(
        self, run_id: str, attempt_no: int, node: str, op_seq: int, fn: Callable[[], T]
    ) -> T:
        """Execute ``fn`` only if ``(run_id, attempt_no, node, op_seq)`` has not already run.

        ``fn``'s return value MUST be JSON-serialisable — it is the durable record that lets a
        resumed run skip re-executing the side effect.
        """

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT result_json FROM operations "
                    "WHERE run_id=? AND attempt_no=? AND node=? AND op_seq=?",
                    (run_id, attempt_no, node, op_seq),
                ).fetchone()
                if row is not None:
                    self._conn.execute("COMMIT")
                    return json.loads(row[0])
                # Claim the key before the side effect so concurrent callers block on the
                # lock / unique constraint instead of double-applying ``fn``.
                self._conn.execute(
                    "INSERT INTO operations (run_id, attempt_no, node, op_seq, result_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_id, attempt_no, node, op_seq, json.dumps({"__pending__": True})),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        result = fn()
        with self._lock:
            self._conn.execute(
                "UPDATE operations SET result_json=? "
                "WHERE run_id=? AND attempt_no=? AND node=? AND op_seq=?",
                (json.dumps(result), run_id, attempt_no, node, op_seq),
            )
            self._conn.commit()
        return result

    def count_for_node(self, run_id: str, attempt_no: int, node: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM operations WHERE run_id=? AND attempt_no=? AND node=?",
                (run_id, attempt_no, node),
            ).fetchone()
        return int(row[0]) if row else 0
