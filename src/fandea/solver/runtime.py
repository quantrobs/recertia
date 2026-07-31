"""Tool invocation runtime with claim scheduling and approval gates (specs §26.2, M2)."""

from __future__ import annotations

import contextvars
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from contracts.resources import ResourceClaim
from fandea.solver.claims import ClaimScheduler
from fandea.solver.registry import ToolRegistry, ToolResult
from fandea.solver.sandbox import SandboxLimits

_ACTIVE_SANDBOX_LIMITS: contextvars.ContextVar[SandboxLimits | None] = contextvars.ContextVar(
    "fandea_active_sandbox_limits", default=None
)


def active_sandbox_limits() -> SandboxLimits:
    """Limits for the in-flight ``ToolRuntime.invoke`` (handlers may read this)."""

    return _ACTIVE_SANDBOX_LIMITS.get() or SandboxLimits.from_policy()


class ApprovalGate(Protocol):
    """Capability required of any approval gate wired into ``ToolRuntime``."""

    def is_approved(self, tool: str, step_id: str) -> bool: ...


class ApprovalRequiredError(PermissionError):
    """Raised when a non-read tool is invoked without an approval grant."""


class ToolRuntime:
    """Invokes registered tools; records affordance-relevant outcomes."""

    def __init__(
        self,
        registry: ToolRegistry,
        scheduler: ClaimScheduler | None = None,
        *,
        require_approval_for_non_read: bool = True,
        approval_gate: ApprovalGate | None = None,
        sandbox_limits: SandboxLimits | None = None,
        sandbox_policy: object | None = None,
    ) -> None:
        self._registry = registry
        self.scheduler = scheduler or ClaimScheduler()
        self._invocations: list[ToolResult] = []
        self.require_approval_for_non_read = require_approval_for_non_read
        self.approval_gate = approval_gate
        if sandbox_limits is not None:
            self.sandbox_limits = sandbox_limits
        else:
            self.sandbox_limits = SandboxLimits.from_policy(sandbox_policy)

    @property
    def invocations(self) -> Sequence[ToolResult]:
        """Read-only view of tool results recorded for this runtime."""

        return tuple(self._invocations)

    def invoke(
        self,
        tool_name: str,
        inputs: dict,
        *,
        workdir: Path,
        step_id: str,
        extra_claims: list[ResourceClaim] | None = None,
    ) -> ToolResult:
        tool = self._registry.get(tool_name)
        if (
            self.require_approval_for_non_read
            and tool.side_effect not in ("read", "pure")
        ):
            gate = self.approval_gate
            if gate is None or not gate.is_approved(tool_name, step_id):
                raise ApprovalRequiredError(
                    f"tool {tool_name!r} side_effect={tool.side_effect!r} requires approval"
                )
        claims = list(tool.claims) + list(extra_claims or [])
        self.scheduler.acquire(step_id, claims)
        started = time.monotonic()
        token = _ACTIVE_SANDBOX_LIMITS.set(self.sandbox_limits)
        try:
            handler = self._registry.handler(tool_name)
            result = handler(inputs, workdir)
            result.duration_s = time.monotonic() - started
            result.claimed = claims
            if not result.ok:
                sig = self._registry.match_error_signature(
                    tool_name, result.stdout + result.stderr
                )
                result.error_signature = sig
            self._invocations.append(result)
            return result
        finally:
            _ACTIVE_SANDBOX_LIMITS.reset(token)
            self.scheduler.release(step_id, claims)

    def is_flaky(self, tool_name: str) -> bool:
        """Read-only tool metadata needed for failure classification."""
        return self._registry.is_flaky(tool_name)

    def names(self) -> list[str]:
        """Read-only names; mutation remains private to the registry owner."""
        return self._registry.names()

    def match_error_signature(self, tool_name: str, output: str) -> str | None:
        """Read-only error metadata; does not expose registry mutation."""
        return self._registry.match_error_signature(tool_name, output)
