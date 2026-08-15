from __future__ import annotations

from pathlib import Path

import pytest

from recertia.workspace import WorkspaceManager


def test_snapshot_and_restore_round_trip(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "a.txt").write_text("original")

    mgr = WorkspaceManager(tmp_path / "snapshots")
    ref = mgr.snapshot(workdir, run_id="r1", attempt_no=0)

    (workdir / "a.txt").write_text("mutated")
    (workdir / "b.txt").write_text("new file")

    mgr.restore(workdir, ref)

    assert (workdir / "a.txt").read_text() == "original"
    assert not (workdir / "b.txt").exists()


def test_restore_unknown_snapshot_raises(tmp_path: Path) -> None:
    mgr = WorkspaceManager(tmp_path / "snapshots")
    with pytest.raises(FileNotFoundError):
        mgr.restore(tmp_path / "work", "does-not-exist")


def test_snapshot_of_empty_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "work"  # never created
    mgr = WorkspaceManager(tmp_path / "snapshots")
    ref = mgr.snapshot(workdir, run_id="r1", attempt_no=0)
    assert mgr.snapshot_path(ref).exists()
