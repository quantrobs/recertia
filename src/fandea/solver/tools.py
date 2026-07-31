"""Tool registry with side-effect classes and declared resource claims (specs §26.2, M2).

The registry *contents* are T3 (code review only — ADR-0005): runs invoke tools through
:class:`ToolRuntime` but never mutate the registry. Mutation APIs live on
:class:`ToolRegistry` and are not injected into ``NodeContext``.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from contracts.resources import ResourceClaim, ResourceConflict

SideEffectClass = Literal["read", "write", "network", "external", "pure"]


@dataclass(frozen=True)
class Tool:
    name: str
    side_effect: SideEffectClass
    claims: tuple[ResourceClaim, ...] = ()
    description: str = ""
    flaky: bool = False
    """When True, classify_failure treats errors from this tool as ``tool`` (not execution)."""

    error_signatures: tuple[str, ...] = ()
    """Substrings that, when present in stderr/stdout, mark a known tool failure mode."""


@dataclass
class ToolResult:
    tool: str
    ok: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    error_signature: str | None = None
    claimed: list[ResourceClaim] = field(default_factory=list)


Handler = Callable[[dict, Path], ToolResult]


class ToolRegistry:
    """Process-global catalogue. Populate at startup; treat as immutable thereafter."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._handlers: dict[str, Handler] = {}

    def register(self, tool: Tool, handler: Handler) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered (T3: no silent overwrite)")
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def handler(self, name: str) -> Handler:
        return self._handlers[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def is_flaky(self, name: str) -> bool:
        tool = self._tools.get(name)
        return bool(tool and tool.flaky)

    def match_error_signature(self, name: str, output: str) -> str | None:
        tool = self._tools.get(name)
        if tool is None:
            return None
        for sig in tool.error_signatures:
            if sig in output:
                return sig
        return None


class ClaimScheduler:
    """Fixed-order claim acquisition with timeout → merge/serialise signal (specs §26.2)."""

    def __init__(self, claim_timeout_s: float = 60.0) -> None:
        self.claim_timeout_s = claim_timeout_s
        self._holders: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()
        self.conflicts: list[ResourceConflict] = []

    @staticmethod
    def sort_key(claim: ResourceClaim) -> tuple[str, str]:
        return (claim.kind, claim.id)

    @staticmethod
    def conflicts_with(a: ResourceClaim, b: ResourceClaim) -> bool:
        if a.kind != b.kind or a.id != b.id:
            return False
        return a.mode in ("write", "exclusive") or b.mode in ("write", "exclusive")

    def acquire(self, step_id: str, claims: list[ResourceClaim]) -> list[ResourceConflict]:
        """Acquire all claims for ``step_id`` in global order. Raises :class:`ClaimTimeoutError`."""

        ordered = sorted(claims, key=self.sort_key)
        acquired: list[ResourceClaim] = []
        waits: list[ResourceConflict] = []
        started = time.monotonic()
        for claim in ordered:
            key = (claim.kind, claim.id)
            while True:
                with self._lock:
                    holder = self._holders.get(key)
                    if holder is None or holder == step_id:
                        self._holders[key] = step_id
                        acquired.append(claim)
                        waited_ms = int((time.monotonic() - started) * 1000)
                        if waited_ms > 0:
                            conflict = ResourceConflict(
                                claim=claim,
                                waiting=step_id,
                                holder=holder or "none",
                                waited_ms=waited_ms,
                                resolution="acquired",
                            )
                            waits.append(conflict)
                            self.conflicts.append(conflict)
                        break
                waited_ms = int((time.monotonic() - started) * 1000)
                if time.monotonic() - started > self.claim_timeout_s:
                    conflict = ResourceConflict(
                        claim=claim,
                        waiting=step_id,
                        holder=holder or "unknown",
                        waited_ms=waited_ms,
                        resolution="timed_out",
                    )
                    self.conflicts.append(conflict)
                    self.release(step_id, acquired)
                    raise ClaimTimeoutError(conflict)
                time.sleep(0.001)
        return waits

    def release(self, step_id: str, claims: list[ResourceClaim]) -> None:
        with self._lock:
            for claim in claims:
                key = (claim.kind, claim.id)
                if self._holders.get(key) == step_id:
                    del self._holders[key]

    def held_by(self) -> dict[tuple[str, str], str]:
        with self._lock:
            return dict(self._holders)


class ClaimTimeoutError(Exception):
    def __init__(self, conflict: ResourceConflict) -> None:
        self.conflict = conflict
        super().__init__(
            f"claim timeout: {conflict.waiting} waited {conflict.waited_ms}ms for "
            f"{conflict.claim.kind}:{conflict.claim.id} held by {conflict.holder}"
        )


class ToolRuntime:
    """Invokes registered tools; records affordance-relevant outcomes."""

    def __init__(self, registry: ToolRegistry, scheduler: ClaimScheduler | None = None) -> None:
        self.registry = registry
        self.scheduler = scheduler or ClaimScheduler()
        self.invocations: list[ToolResult] = []

    def invoke(
        self,
        tool_name: str,
        inputs: dict,
        *,
        workdir: Path,
        step_id: str,
        extra_claims: list[ResourceClaim] | None = None,
    ) -> ToolResult:
        tool = self.registry.get(tool_name)
        claims = list(tool.claims) + list(extra_claims or [])
        self.scheduler.acquire(step_id, claims)
        started = time.monotonic()
        try:
            result = self.registry.handler(tool_name)(inputs, workdir)
            result.duration_s = time.monotonic() - started
            result.claimed = claims
            if not result.ok:
                sig = self.registry.match_error_signature(
                    tool_name, result.stdout + result.stderr
                )
                result.error_signature = sig
            self.invocations.append(result)
            return result
        finally:
            self.scheduler.release(step_id, claims)


def default_registry() -> ToolRegistry:
    """First-domain tools for repo-chore (shell, edit_file, read_file, grep)."""

    registry = ToolRegistry()

    def shell_handler(inputs: dict, workdir: Path) -> ToolResult:
        command = str(inputs.get("command", "true"))
        proc = subprocess.run(
            command, shell=True, cwd=workdir, capture_output=True, text=True, timeout=60
        )
        return ToolResult(
            tool="shell",
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout[-8000:],
            stderr=proc.stderr[-8000:],
        )

    def edit_file_handler(inputs: dict, workdir: Path) -> ToolResult:
        path = workdir / str(inputs["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(inputs.get("content", "")))
        return ToolResult(tool="edit_file", ok=True, stdout=f"wrote {path}")

    def read_file_handler(inputs: dict, workdir: Path) -> ToolResult:
        path = workdir / str(inputs["path"])
        if not path.exists():
            return ToolResult(
                tool="read_file", ok=False, exit_code=1, stderr=f"missing {path}"
            )
        return ToolResult(tool="read_file", ok=True, stdout=path.read_text()[-8000:])

    def grep_handler(inputs: dict, workdir: Path) -> ToolResult:
        pattern = str(inputs.get("pattern", ""))
        path = workdir / str(inputs.get("path", "."))
        proc = subprocess.run(
            ["grep", "-R", "-n", pattern, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # grep exit 1 = no match; treat as ok with empty stdout for skill use.
        return ToolResult(
            tool="grep",
            ok=proc.returncode in (0, 1),
            exit_code=proc.returncode,
            stdout=proc.stdout[-8000:],
            stderr=proc.stderr[-8000:],
        )

    registry.register(
        Tool(name="shell", side_effect="write", description="Run a shell command"),
        shell_handler,
    )
    registry.register(
        Tool(
            name="edit_file",
            side_effect="write",
            description="Write file contents",
            claims=(ResourceClaim(kind="file", id="*", mode="write"),),
        ),
        edit_file_handler,
    )
    registry.register(
        Tool(name="read_file", side_effect="read", description="Read a file"),
        read_file_handler,
    )
    registry.register(
        Tool(name="grep", side_effect="read", description="Search files"),
        grep_handler,
    )
    return registry
