"""Regression tests for snapshot symlink exfil and run_id path escape."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from recertia.ids import InvalidIdError, validate_run_id
from recertia.paths import PathEscapeError, contained_path
from recertia.workspace import WorkspaceManager
from tests.support.symlinks import require_symlink_support


def test_validate_run_id_rejects_path_escape() -> None:
    with pytest.raises(InvalidIdError):
        validate_run_id("../escape")
    with pytest.raises(InvalidIdError):
        validate_run_id("/abs")
    assert validate_run_id("run-ok_1.2") == "run-ok_1.2"


def test_contained_path_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    with pytest.raises(PathEscapeError):
        contained_path(root, "..", "outside")


def test_snapshot_skips_outbound_symlink_exfil(tmp_path: Path) -> None:
    require_symlink_support(tmp_path)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    secret_file = secrets / "api_keys.sqlite"
    secret_file.write_text("TOP-SECRET-KEY-MATERIAL", encoding="utf-8")

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "readme.txt").write_text("ok", encoding="utf-8")
    # Relative link that resolves outside the workdir.
    os.symlink(os.path.relpath(secret_file, workdir), workdir / "stolen")

    snaps = tmp_path / "snapshots"
    mgr = WorkspaceManager(snaps)
    ref = mgr.snapshot(workdir, "run-safe", 1)
    snap_dir = mgr.snapshot_path(ref)

    # Outbound symlink must not appear in the snapshot (skipped).
    assert not (snap_dir / "stolen").exists()
    assert not (snap_dir / "stolen").is_symlink()
    assert (snap_dir / "readme.txt").read_text(encoding="utf-8") == "ok"
    # Secret bytes must not appear anywhere under the snapshot store.
    for path in snap_dir.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert "TOP-SECRET" not in path.read_text(encoding="utf-8", errors="ignore")

    restored = tmp_path / "restored"
    mgr.restore(restored, ref)
    assert not (restored / "stolen").exists()
    assert (restored / "readme.txt").read_text(encoding="utf-8") == "ok"


def test_snapshot_preserves_internal_relative_symlink(tmp_path: Path) -> None:
    require_symlink_support(tmp_path)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "target.txt").write_text("inside", encoding="utf-8")
    os.symlink("target.txt", workdir / "link.txt")

    mgr = WorkspaceManager(tmp_path / "snapshots")
    ref = mgr.snapshot(workdir, "run-link", 1)
    snap = mgr.snapshot_path(ref)
    assert (snap / "link.txt").is_symlink()
    assert os.readlink(snap / "link.txt") == "target.txt"


def test_snapshot_rejects_escaping_run_id(tmp_path: Path) -> None:
    mgr = WorkspaceManager(tmp_path / "snapshots")
    workdir = tmp_path / "wd"
    workdir.mkdir()
    with pytest.raises(InvalidIdError):
        mgr.snapshot(workdir, "../escape", 1)


def test_restore_rejects_escaping_snapshot_ref(tmp_path: Path) -> None:
    mgr = WorkspaceManager(tmp_path / "snapshots")
    with pytest.raises(PathEscapeError):
        mgr.restore(tmp_path / "wd", "../escape-attempt1-deadbeef")
