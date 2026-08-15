"""Platform-specific pytest helpers for Windows / POSIX differences."""

from __future__ import annotations

import sys

import pytest

skip_posix_mode_bits = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits are not enforced on Windows/NTFS",
)
