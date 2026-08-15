"""Retention / garbage collection for run artifacts (snapshots, transcripts, workspaces)."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from recertia.workspace import WorkspaceManager


@dataclass(frozen=True)
class GcReport:
    snapshots: list[str]
    transcripts: list[str]
    workspaces: list[str]

    @property
    def total(self) -> int:
        return len(self.snapshots) + len(self.transcripts) + len(self.workspaces)


def garbage_collect(
    runs_root: Path | str,
    *,
    older_than_days: float = 14.0,
    dry_run: bool = False,
) -> GcReport:
    """Remove aged artifacts under ``runs_root`` (snapshots, transcripts, workspaces)."""

    root = Path(runs_root)
    snapshots = WorkspaceManager(root / "snapshots").gc(
        older_than_days=older_than_days, dry_run=dry_run
    )
    transcripts = _gc_named_children(
        root / "transcripts", older_than_days=older_than_days, dry_run=dry_run
    )
    workspaces = _gc_named_children(
        root / "workspaces", older_than_days=older_than_days, dry_run=dry_run
    )
    return GcReport(snapshots=snapshots, transcripts=transcripts, workspaces=workspaces)


def _gc_named_children(
    directory: Path,
    *,
    older_than_days: float,
    dry_run: bool,
) -> list[str]:
    cutoff = time.time() - (older_than_days * 86400.0)
    removed: list[str] = []
    if not directory.exists():
        return removed
    for child in sorted(directory.iterdir()):
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        removed.append(child.name)
        if dry_run:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    return removed
