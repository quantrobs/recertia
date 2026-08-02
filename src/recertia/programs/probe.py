"""Read-only workspace probe for Compose / program drafting (GP0.5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_ALLOWED_NAMES = {
    "pyproject.toml",
    "pytest.ini",
    "README.md",
    ".gitignore",
    ".editorconfig",
    "Makefile",
    "src",
    "tests",
}


def probe_workdir(root: Path, *, max_entries: int = 40) -> dict[str, Any]:
    """Inventory allowlisted paths under a tenant workspace root (no writes, no exec)."""

    root = root.resolve()
    if not root.is_dir():
        return {"exists": False, "paths": [], "tests": []}

    paths: list[dict[str, Any]] = []
    for name in sorted(_ALLOWED_NAMES):
        p = root / name
        if p.exists():
            paths.append(
                {
                    "path": name,
                    "is_dir": p.is_dir(),
                    "is_file": p.is_file(),
                }
            )

    tests: list[str] = []
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for p in sorted(tests_dir.rglob("test_*.py")):
            try:
                rel = str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            tests.append(rel)
            if len(tests) >= max_entries:
                break

    return {
        "exists": True,
        "root": str(root),
        "paths": paths,
        "tests": tests,
    }
