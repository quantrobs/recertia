"""Path containment helpers — refuse escapes outside an allowed root."""

from __future__ import annotations

from pathlib import Path


class PathEscapeError(ValueError):
    """Raised when a resolved path escapes its allowed root."""


def contained_path(root: Path | str, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and require the result stay inside ``root``.

    Symlink components are resolved before the containment check.
    """

    base = Path(root).resolve()
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise PathEscapeError(f"path {candidate} escapes root {base}") from exc
    return candidate


def is_within(root: Path | str, path: Path | str) -> bool:
    """Return True when ``path`` resolves inside ``root``."""

    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False
