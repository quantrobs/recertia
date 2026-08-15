"""Operator-GA scaffolding: backup/restore, tabletop walker, live canary."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from recertia.cli.main import app
from recertia.evals.canary import LiveCanaryError, run_judge_canary, run_live_verifier_canary
from recertia.ops.backup import BackupError, backup_tree, restore_tree
from recertia.solver.model import StubModelClient

runner = CliRunner()


def test_backup_round_trip_and_refuses_escape(tmp_path: Path) -> None:
    root = tmp_path / "recertia"
    (root / "runs").mkdir(parents=True)
    (root / "runs" / "note.txt").write_text("keep-me\n", encoding="utf-8")
    archive = tmp_path / "backups" / "recertia.tar.gz"
    backup_tree(root, archive)
    dest = tmp_path / "restored"
    restore_tree(archive, dest)
    assert (dest / "runs" / "note.txt").read_text(encoding="utf-8") == "keep-me\n"

    nested = root / "inside.tar.gz"
    try:
        backup_tree(root, nested)
        raise AssertionError("expected BackupError for archive inside root")
    except BackupError:
        pass

    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        payload = b"nope"
        info = tarfile.TarInfo(name="../escaped.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    dest_escape = tmp_path / "restore-escape"
    dest_escape.mkdir()
    try:
        restore_tree(evil, dest_escape)
        raise AssertionError("expected BackupError for path-escaping member")
    except BackupError:
        pass
    assert not (tmp_path / "escaped.txt").exists()


def test_backup_cli(tmp_path: Path) -> None:
    root = tmp_path / ".recertia"
    root.mkdir()
    (root / "x").write_text("y", encoding="utf-8")
    archive = tmp_path / "out.tar.gz"
    created = runner.invoke(
        app, ["backup", "create", "--root", str(root), "--output", str(archive)]
    )
    assert created.exit_code == 0, created.output
    archive_default = tmp_path / "out-default.tar.gz"
    created_default = runner.invoke(
        app, ["backup", "--root", str(root), "--output", str(archive_default)]
    )
    assert created_default.exit_code == 0, created_default.output
    dest = tmp_path / "restored"
    restored = runner.invoke(app, ["restore", str(archive), "--dest", str(dest)])
    assert restored.exit_code == 0, restored.output
    assert (dest / "x").read_text(encoding="utf-8") == "y"


def test_tabletop_walks_run_and_restore(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    spec = {
        "task": {"request": "write output.txt"},
        "criteria": [
            {
                "id": "output-exists",
                "kind": "command",
                "run": "test -f output.txt",
                "source": "caller",
                "weight": 1.0,
                "sensitivity_proof": {
                    "criterion_id": "output-exists",
                    "negative_fixture": "empty workspace",
                    "rejected": True,
                    "checked_at": "2026-01-01T00:00:00Z",
                },
            }
        ],
        "script": ["python3 -c \"open('output.txt','w').write('done')\""],
        "workdir": str(workdir),
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    runs_root = tmp_path / "runs"
    run = runner.invoke(
        app,
        ["run", "--spec", str(spec_path), "--runs-root", str(runs_root), "--run-id", "tt-run-1"],
    )
    assert run.exit_code == 0, run.output

    archive = tmp_path / "backup.tar.gz"
    backup_tree(runs_root, archive)
    log_path = tmp_path / "tabletop.json"
    result = runner.invoke(
        app,
        [
            "tabletop",
            "tt-run-1",
            "--runs-root",
            str(runs_root),
            "--restore-from",
            str(archive),
            "--restore-dest",
            str(tmp_path / "restored-runs"),
            "--follow-up",
            "accepted restore path",
            "--output",
            str(log_path),
        ],
    )
    assert result.exit_code == 0, result.output
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["run_id"] == "tt-run-1"
    assert log["ga_claimed"] is False
    assert log["restore_ok"] is True
    assert log["terminal"] == "solved"
    assert log["navigable"] is True
    assert (tmp_path / "restored-runs").is_dir()


def test_synthetic_canary_and_live_stub_verifier() -> None:
    synthetic = run_judge_canary()
    assert synthetic.trials >= 1
    assert synthetic.false_passes == 0
    assert synthetic.mode == "synthetic"

    fail_client = StubModelClient(responses=["FAIL"], provider="stub", model_id="canary-v")
    live = run_live_verifier_canary(verifier=fail_client, model_version="stub × canary-v")
    assert live.mode == "live"
    assert live.trials >= 1
    assert live.false_passes == 0
    assert live.attribution == "stub × canary-v"

    pass_client = StubModelClient(responses=["PASS"], provider="stub", model_id="canary-v")
    poisoned = run_live_verifier_canary(verifier=pass_client, model_version="stub × canary-v")
    assert poisoned.false_passes >= 1


def test_live_canary_cli_refuses_without_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECERTIA_VERIFIER_MODEL_ID", raising=False)
    monkeypatch.delenv("RECERTIA_MODEL_PROVIDER", raising=False)
    result = runner.invoke(app, ["canary", "--live"])
    assert result.exit_code == 2
    assert "RECERTIA_VERIFIER_MODEL_ID" in result.output

    synthetic = runner.invoke(app, ["canary"])
    assert synthetic.exit_code == 0, synthetic.output
    payload = json.loads(synthetic.output)
    assert payload["a4_updated"] is False
    assert payload["trials"] >= 1


def test_live_canary_error_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECERTIA_VERIFIER_MODEL_ID", raising=False)
    monkeypatch.setenv("RECERTIA_MODEL_PROVIDER", "stub")
    try:
        run_live_verifier_canary()
        raise AssertionError("expected LiveCanaryError")
    except LiveCanaryError:
        pass


def test_weekly_ops_does_not_swallow_failures() -> None:
    text = Path(".github/workflows/weekly-ops.yml").read_text(encoding="utf-8")
    assert "|| true" not in text
    assert "recertia eval run" in text
    assert "recertia canary" in text
    assert "RECERTIA_VERIFIER_MODEL_ID" in text
