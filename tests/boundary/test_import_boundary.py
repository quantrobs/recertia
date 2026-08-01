"""Statically enforces ADR-0005's T3 boundary: nothing a run or job can invoke may import a
T3 module (the eval harness, ablation sampler, promotion thresholds, sandbox policy, or this
boundary itself). Parses the AST rather than trusting convention, per the ADR's own mandate
("enforced by module boundaries and asserted in CI, not by convention").

``recertia.jobs`` and ``recertia.evals.ablation`` are scanned once present; this test covers
them by globbing rather than hardcoding paths.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from recertia.governance import T3_FORBIDDEN_FOR_RUNS_AND_JOBS

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED_PACKAGES = ("recertia/nodes", "recertia/jobs")


def _imported_module_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _guarded_files() -> list[Path]:
    files: list[Path] = []
    for pkg in GUARDED_PACKAGES:
        pkg_dir = REPO_ROOT / "src" / pkg
        if pkg_dir.exists():
            files.extend(pkg_dir.rglob("*.py"))
    return files


@pytest.mark.parametrize("source_path", _guarded_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_t3_imports_in_runs_or_jobs(source_path: Path) -> None:
    imported = _imported_module_names(source_path)
    for forbidden in T3_FORBIDDEN_FOR_RUNS_AND_JOBS:
        violating = {
            name
            for name in imported
            if name == forbidden or name.startswith(forbidden + ".")
        }
        assert not violating, (
            f"{source_path.relative_to(REPO_ROOT)} imports {violating}, which is forbidden "
            f"under ADR-0005: T3 surfaces must be unreachable from any code path a run or job "
            f"can invoke."
        )


def test_guarded_files_is_non_empty() -> None:
    """A guard against this test silently checking nothing (e.g. a path typo)."""

    assert _guarded_files(), "expected at least recertia/nodes/*.py to exist and be scanned"
