"""Snapshot and restore a run's workspace between attempts (specs §17).

M0's isolation model: copy the live workspace directory tree into a content-addressed
snapshot directory before every attempt; ``evolve`` restores from the most recent snapshot
before re-dispatching to ``solve``, so every retry starts from a byte-identical clean state
regardless of what the previous attempt left behind — including a half-applied edit or a
partially-run tool sequence.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


class WorkspaceManager:
    """Owns the snapshot store for one run's attempts.

    Snapshots are plain directory copies, not git worktrees or content-addressed blobs — the
    cheapest mechanism that is still correct. A later milestone MAY swap in git worktrees
    without changing this class's interface (``snapshot`` / ``restore`` / ``snapshot_path``).

    ``restore`` mirrors the snapshot into the workdir instead of wiping and re-copying:
    files whose ``(size, mtime_ns)`` still match the snapshot are left untouched, so a
    rollback after a small edit costs a handful of writes rather than a full tree copy.
    Because snapshots are written with ``copy2`` (mtime-preserving), any file the attempt
    did not touch still carries the snapshot's exact stat and is skipped; anything written,
    created, or deleted by the attempt is reverted.
    """

    def __init__(self, snapshots_root: Path | str) -> None:
        self._snapshots_root = Path(snapshots_root)
        self._snapshots_root.mkdir(parents=True, exist_ok=True)

    def snapshot(self, workdir: Path, run_id: str, attempt_no: int) -> str:
        """Copy ``workdir`` into a new snapshot; return its ``snapshot_ref``."""

        ref = f"{run_id}-attempt{attempt_no}-{uuid.uuid4().hex[:8]}"
        dest = self._snapshots_root / ref
        if workdir.exists():
            shutil.copytree(workdir, dest, dirs_exist_ok=True)
        else:
            dest.mkdir(parents=True, exist_ok=True)
        return ref

    def restore(self, workdir: Path, snapshot_ref: str) -> None:
        """Make ``workdir`` an exact mirror of ``snapshot_ref``, with minimal writes."""

        src = self._snapshots_root / snapshot_ref
        if not src.exists():
            raise FileNotFoundError(f"snapshot {snapshot_ref!r} not found under {self._snapshots_root}")
        if not workdir.exists():
            workdir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, workdir)
            return
        _sync_directory(src, workdir)

    def snapshot_path(self, snapshot_ref: str) -> Path:
        return self._snapshots_root / snapshot_ref


def _sync_directory(src: Path, dst: Path) -> None:
    """Mirror ``src`` into ``dst``: delete what src lacks, rewrite only changed files."""

    dst.mkdir(parents=True, exist_ok=True)

    src_dirs: set[str] = set()
    src_files: dict[str, Path] = {}
    for root, dirnames, filenames in os.walk(src):
        rel_root = os.path.relpath(root, src)
        for name in dirnames:
            src_dirs.add(os.path.normpath(os.path.join(rel_root, name)))
        for name in filenames:
            src_files[os.path.normpath(os.path.join(rel_root, name))] = Path(root) / name

    # Remove dst entries the snapshot does not have. Bottom-up so stale directories
    # are empty (or gone) by the time their parent is considered.
    for root, dirnames, filenames in os.walk(dst, topdown=False, followlinks=False):
        rel_root = os.path.relpath(root, dst)
        for name in filenames:
            rel = os.path.normpath(os.path.join(rel_root, name))
            dst_file = Path(root) / name
            if rel not in src_files or dst_file.is_symlink():
                dst_file.unlink(missing_ok=True)
        for name in dirnames:
            rel = os.path.normpath(os.path.join(rel_root, name))
            dst_dir = Path(root) / name
            if dst_dir.is_symlink():
                dst_dir.unlink()
            elif rel not in src_dirs:
                shutil.rmtree(dst_dir, ignore_errors=True)

    for rel in sorted(src_dirs):
        target = dst / rel
        if target.is_symlink():
            target.unlink()
        target.mkdir(parents=True, exist_ok=True)
    for rel, src_file in src_files.items():
        dst_file = dst / rel
        if _unchanged(src_file, dst_file):
            continue
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)


def _unchanged(src_file: Path, dst_file: Path) -> bool:
    """Same size and mtime: the attempt left this file alone (snapshot copies keep mtimes)."""

    try:
        if dst_file.is_symlink():
            return False
        src_stat = src_file.stat()
        dst_stat = dst_file.stat()
    except OSError:
        return False
    return src_stat.st_size == dst_stat.st_size and src_stat.st_mtime_ns == dst_stat.st_mtime_ns
