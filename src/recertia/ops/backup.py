"""Backup and restore for the ``.recertia/`` durability unit (operator GA / RPO ≤ 24h)."""

from __future__ import annotations

import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BackupError(ValueError):
    """Invalid backup or restore arguments."""


def default_archive_name(*, at: datetime | None = None) -> str:
    stamp = (at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"recertia-{stamp}.tar.gz"


def backup_tree(root: Path, archive: Path) -> Path:
    """Write a gzip tar of ``root`` (the whole ``.recertia/`` tree)."""

    source = Path(root).resolve()
    dest = Path(archive).resolve()
    if not source.is_dir():
        raise BackupError(f"backup root does not exist: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.relative_to(source)
    except ValueError:
        pass
    else:
        raise BackupError("archive path must not be inside the backup root")
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(source, arcname=".")
    return dest


def restore_tree(archive: Path, dest: Path, *, overwrite: bool = False) -> Path:
    """Extract a backup archive into ``dest``. Refuses path-escaping members."""

    src = Path(archive).resolve()
    target = Path(dest).resolve()
    if not src.is_file():
        raise BackupError(f"archive not found: {src}")
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise BackupError(f"restore dest is not empty: {target} (pass overwrite=True)")
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(src, "r:*") as tar:
        members: list[tarfile.TarInfo] = []
        for member in tar.getmembers():
            name = member.name.lstrip("/")
            if name not in {"", "."}:
                candidate = (target / name).resolve()
                try:
                    candidate.relative_to(target)
                except ValueError as exc:
                    raise BackupError(f"archive member escapes dest: {member.name}") from exc
            members.append(member)
        extract_kw: dict[str, Any] = {"path": target, "members": members}
        if hasattr(tarfile, "data_filter"):
            extract_kw["filter"] = "data"
        tar.extractall(**extract_kw)
    return target
