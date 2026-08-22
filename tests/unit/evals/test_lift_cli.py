from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from contracts.eval import EvalObservation
from recertia.cli.main import app
from recertia.evals.store import EvalStore

runner = CliRunner()


def _obs(run_id: str, *, arm: str, success: bool, snapshot_id: str = "snap") -> EvalObservation:
    return EvalObservation(
        run_id=run_id,
        task_class="repo-chore",
        arm=arm,  # type: ignore[arg-type]
        snapshot_id=snapshot_id,
        first_attempt_success=success,
        is_eval_fixture=False,
        recorded_at=datetime.now(timezone.utc),
        evidence_hash=f"hash-{run_id}",
    )


def test_lift_cli_reports_variance_and_refuses_low_run_count(tmp_path: Path) -> None:
    db = tmp_path / "evals.db"
    store = EvalStore(db)
    for i in range(4):
        store._append_observation(_obs(f"t{i}", arm="treatment", success=True, snapshot_id=f"s{i}"))
        store._append_observation(_obs(f"c{i}", arm="control", success=False, snapshot_id=f"s{i}"))
    store.close()

    result = runner.invoke(
        app, ["lift", "--task-class", "repo-chore", "--eval-db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "independent_runs=4" in result.output
    assert "status=low run count" in result.output
    assert "treatment_variance" in result.output
    assert "never claims established lift" in result.output


def test_lift_cli_establishes_on_hundred_trials(tmp_path: Path) -> None:
    db = tmp_path / "evals.db"
    store = EvalStore(db)
    for i in range(100):
        store._append_observation(_obs(f"t{i}", arm="treatment", success=i < 80))
        store._append_observation(_obs(f"c{i}", arm="control", success=i < 50))
    store.close()

    result = runner.invoke(
        app, ["lift", "--task-class", "repo-chore", "--eval-db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "independent_runs=100" in result.output
    assert "status=established positive" in result.output
