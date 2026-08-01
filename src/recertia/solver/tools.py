"""Tool registry, claims, and runtime — public facade (specs §26.2, M2).

Ownership lives in :mod:`recertia.solver.registry`, :mod:`recertia.solver.claims`, and
:mod:`recertia.solver.runtime`. This module re-exports the historical public surface so
existing ``from recertia.solver.tools import …`` imports keep working.
"""

from __future__ import annotations

from recertia.solver.claims import ClaimScheduler, ClaimTimeoutError
from recertia.solver.registry import (
    Handler,
    SideEffectClass,
    Tool,
    ToolRegistry,
    ToolResult,
    default_registry,
)
from recertia.solver.runtime import (
    ApprovalGate,
    ApprovalRequiredError,
    StepInvokeContext,
    ToolRuntime,
    active_model,
    active_sandbox_limits,
    active_step_context,
)

__all__ = [
    "ApprovalGate",
    "StepInvokeContext",
    "active_model",
    "active_sandbox_limits",
    "active_step_context",
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
