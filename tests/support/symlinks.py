"""Probe whether the host can create symlinks (Windows Developer Mode / privilege)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def require_symlink_support(tmp_path: Path) -> None:
    """Skip the calling test when symlink creation is denied (WinError 1314)."""

    probe_dir = tmp_path / "_symlink_probe"
    probe_dir.mkdir(exist_ok=True)
    target = probe_dir / "target.txt"
    link = probe_dir / "link.txt"
    target.write_text("ok", encoding="utf-8")
    try:
        os.symlink("target.txt", link)
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        # 1314: ERROR_PRIVILEGE_NOT_HELD — common without Developer Mode.
        if sys.platform == "win32" and winerror == 1314:
            pytest.skip(
                "symlink privilege required (enable Windows Developer Mode "
                "or SeCreateSymbolicLinkPrivilege)"
            )
        if isinstance(exc, (NotImplementedError, OSError)) and sys.platform == "win32":
            pytest.skip(f"symlink creation unsupported on this host: {exc}")
        raise
    finally:
        if link.exists() or link.is_symlink():
            link.unlink(missing_ok=True)
        if target.exists():
            target.unlink(missing_ok=True)
