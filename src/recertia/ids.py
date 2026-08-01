"""Shared identifier validation (run_id and related path-safe tokens)."""

from __future__ import annotations

import re

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class InvalidIdError(ValueError):
    """Raised when a caller-supplied id is not path-safe."""


def validate_run_id(run_id: str) -> str:
    """Require a path-safe run id (no ``..``, separators, or absolute forms)."""

    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise InvalidIdError(
            "run_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
        )
    return run_id
