"""Statically enforces the single-writer rule for run spend (specs §10.1, §18).

Spend accounting was previously hand-rolled at every solve exit, and each site chose which
dimensions to charge: wall clock went uncharged everywhere, one budget-exhaustion path
discarded the work it had already done, and the paths that did charge tokens read cumulative
run-scoped counters as if they were attempt deltas.

Rather than trusting that the next exit path remembers all five dimensions, this parses the
AST: ``recertia.nodes.attempt`` is the only module allowed to write ``RunState.spent``, and
the only one allowed to read the run-scoped counters an attempt delta must be derived from.

A branch's own ``spent`` field is out of scope — that is the branch's lease, not run spend.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NODES_DIR = REPO_ROOT / "src" / "recertia" / "nodes"
ACCOUNTING_MODULE = NODES_DIR / "attempt.py"

RUN_STATE_NAMES = {"state", "new_state"}

CUMULATIVE_RUNTIME_COUNTERS = {
    "ctx.model.spend": "ModelClient.spend accumulates over the whole run",
    "ctx.tools.invocations": "ToolRuntime.invocations accumulates over the whole run",
    "ctx.tools.scheduler.conflicts": "ClaimScheduler.conflicts accumulates over the whole run",
}


def _node_modules() -> list[Path]:
    return sorted(p for p in NODES_DIR.rglob("*.py") if p != ACCOUNTING_MODULE)


def _parse(source_path: Path) -> ast.Module:
    return ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))


def _attribute_path(node: ast.Attribute) -> str | None:
    """Render ``ctx.tools.scheduler.conflicts`` from nested attribute access, else ``None``."""

    parts = [node.attr]
    current: ast.expr = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _run_spend_writes(tree: ast.Module) -> list[int]:
    """Lines where ``state.model_copy`` updates the ``spent`` field."""

    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "model_copy":
            continue
        if not isinstance(func.value, ast.Name) or func.value.id not in RUN_STATE_NAMES:
            continue
        for keyword in node.keywords:
            if keyword.arg != "update" or not isinstance(keyword.value, ast.Dict):
                continue
            lines.extend(
                key.lineno
                for key in keyword.value.keys
                if isinstance(key, ast.Constant) and key.value == "spent"
            )
    return lines


def _cumulative_counter_reads(tree: ast.Module) -> list[tuple[int, str]]:
    return [
        (node.lineno, path)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and (path := _attribute_path(node)) in CUMULATIVE_RUNTIME_COUNTERS
    ]


def test_accounting_module_exists() -> None:
    """A guard against this test silently checking nothing (e.g. a rename)."""

    assert ACCOUNTING_MODULE.exists()
    assert _node_modules(), "expected sibling node modules to scan"


def test_the_guard_detects_the_patterns_it_forbids() -> None:
    """The AST matchers are specific enough to have false negatives; prove they still fire."""

    offending = ast.parse(
        "def f(state, ctx):\n"
        "    n = len(ctx.tools.invocations) + ctx.model.spend.tokens\n"
        "    n += len(ctx.tools.scheduler.conflicts)\n"
        "    return state.model_copy(update={'spent': n})\n"
    )

    assert _run_spend_writes(offending)
    assert {path for _, path in _cumulative_counter_reads(offending)} == set(
        CUMULATIVE_RUNTIME_COUNTERS
    )


def test_branch_lease_writes_are_not_treated_as_run_spend() -> None:
    """A branch charging its own lease is legitimate and must not trip the guard."""

    allowed = ast.parse(
        "def f(branch, projected):\n    return branch.model_copy(update={'spent': projected})\n"
    )

    assert not _run_spend_writes(allowed)


@pytest.mark.parametrize("source_path", _node_modules(), ids=lambda p: p.name)
def test_only_the_accounting_module_writes_run_spend(source_path: Path) -> None:
    lines = _run_spend_writes(_parse(source_path))

    assert not lines, (
        f"{source_path.relative_to(REPO_ROOT)} writes RunState.spent directly at line(s) "
        f"{lines}. Charge through recertia.nodes.attempt.AttemptMeter instead, so no exit "
        f"path can silently omit a budget dimension."
    )


@pytest.mark.parametrize("source_path", _node_modules(), ids=lambda p: p.name)
def test_nodes_do_not_read_cumulative_runtime_counters(source_path: Path) -> None:
    reads = _cumulative_counter_reads(_parse(source_path))

    assert not reads, (
        f"{source_path.relative_to(REPO_ROOT)} reads a run-scoped counter as an attempt "
        f"delta at {reads}: "
        + "; ".join(f"{path} — {CUMULATIVE_RUNTIME_COUNTERS[path]}" for _, path in reads)
        + ". Use recertia.nodes.attempt.RuntimeWindow, which reports the difference."
    )
