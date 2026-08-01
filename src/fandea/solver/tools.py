"""Tool registry, claims, and runtime — public facade (specs §26.2, M2).

Ownership lives in :mod:`fandea.solver.registry`, :mod:`fandea.solver.claims`, and
:mod:`fandea.solver.runtime`. This module re-exports the historical public surface so
existing ``from fandea.solver.tools import …`` imports keep working.
"""

from __future__ import annotations

from fandea.solver.claims import ClaimScheduler, ClaimTimeoutError
from fandea.solver.registry import (
    Handler,
    SideEffectClass,
    Tool,
    ToolRegistry,
    ToolResult,
    default_registry,
)
from fandea.solver.runtime import (
    ApprovalGate,
    ApprovalRequiredError,
    ToolRuntime,
    active_sandbox_limits,
)

__all__ = [
    "ApprovalGate",
    "active_sandbox_limits",
    "ApprovalRequiredError",
    "ClaimScheduler",
    "ClaimTimeoutError",
    "Handler",
    "SideEffectClass",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "ToolRuntime",
    "default_registry",
]
