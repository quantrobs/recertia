"""Snapshot and restore a run's workspace between attempts (specs §17).

M0's isolation model: copy the live workspace directory tree into a content-addressed
snapshot directory before every attempt; ``evolve`` restores from the most recent snapshot
before re-dispatching to ``solve``, so every retry starts from a byte-identical clean state
regardless of what the previous attempt left behind — including a half-applied edit or a
partially-run tool sequence.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path


class WorkspaceManager:
    """Owns the snapshot store for one run's attempts.

    Snapshots are plain directory copies, not git worktrees or content-addressed blobs — the
    cheapest mechanism that is still correct. A later milestone MAY swap in git worktrees
    without changing this class's interface (``snapshot`` / ``restore`` / ``snapshot_path``).
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
        """Wipe ``workdir`` and replace it with the contents of ``snapshot_ref``."""

        src = self._snapshots_root / snapshot_ref
        if not src.exists():
            raise FileNotFoundError(f"snapshot {snapshot_ref!r} not found under {self._snapshots_root}")
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, workdir)

    def snapshot_path(self, snapshot_ref: str) -> Path:
        return self._snapshots_root / snapshot_ref
