from __future__ import annotations

from pathlib import Path

from fandea.graph.ops import OperationLedger


def test_run_once_executes_exactly_once_across_calls(tmp_path: Path) -> None:
    ops = OperationLedger(tmp_path / "ops.db")
    calls = []

    def fn():
        calls.append(1)
        return {"value": len(calls)}

    r1 = ops.run_once("run-1", 1, "solve", 0, fn)
    r2 = ops.run_once("run-1", 1, "solve", 0, fn)  # same key: must not call fn again

    assert r1 == r2 == {"value": 1}
    assert len(calls) == 1


def test_different_keys_execute_independently(tmp_path: Path) -> None:
    ops = OperationLedger(tmp_path / "ops.db")
    calls = []

    def fn():
        calls.append(1)
        return len(calls)

    ops.run_once("run-1", 1, "solve", 0, fn)
    ops.run_once("run-1", 1, "solve", 1, fn)  # different op_seq
    ops.run_once("run-1", 2, "solve", 0, fn)  # different attempt_no
    ops.run_once("run-2", 1, "solve", 0, fn)  # different run_id

    assert len(calls) == 4


def test_survives_a_new_ledger_instance_on_the_same_db(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.db"
    calls = []

    def fn():
        calls.append(1)
        return "done"

    OperationLedger(db_path).run_once("run-1", 1, "solve", 0, fn)
    # A brand-new instance (as a resumed process would create) must see the prior result.
    result = OperationLedger(db_path).run_once("run-1", 1, "solve", 0, fn)

    assert result == "done"
    assert len(calls) == 1
