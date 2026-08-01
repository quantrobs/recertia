"""Tool catalogue: side-effect classes, handlers, default first-domain tools (specs §26.2, M2).

The registry *contents* are T3 (code review only — ADR-0005): runs invoke tools through
:class:`~fandea.solver.runtime.ToolRuntime` but never mutate the registry. Mutation APIs
live on :class:`ToolRegistry` and are not injected into ``NodeContext``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from contracts.resources import ResourceClaim

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

_GREP_MAX_FILE_BYTES = 2 * 1024 * 1024
"""Files larger than this are skipped by the in-process grep tool (vendored bundles, blobs)."""

_READ_FILE_TAIL_BYTES = 64 * 1024
"""read_file returns only a tail slice; files beyond this size are read from the end."""


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


def default_registry() -> ToolRegistry:
    """First-domain tools for repo-chore (shell, edit_file, read_file, grep)."""

    registry = ToolRegistry()

    def shell_handler(inputs: dict, workdir: Path) -> ToolResult:
        from fandea.solver.container import run_configured_command
        from fandea.solver.runtime import active_sandbox_limits
        from fandea.solver.sandbox import SandboxError

        command = str(inputs.get("command", "true"))
        limits = active_sandbox_limits()
        try:
            proc = run_configured_command(
                command, workdir=workdir, limits=limits, timeout_s=60
            )
        except SandboxError as exc:
            return ToolResult(tool="shell", ok=False, exit_code=126, stderr=str(exc))
        return ToolResult(
            tool="shell",
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout[-8000:],
            stderr=proc.stderr[-8000:],
        )

    def confined_path(workdir: Path, value: object) -> Path:
        root = workdir.resolve()
        path = (root / str(value)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PermissionError(f"path escapes workspace: {value!r}") from exc
        return path

    def edit_file_handler(inputs: dict, workdir: Path) -> ToolResult:
        path = confined_path(workdir, inputs["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(inputs.get("content", "")))
        return ToolResult(tool="edit_file", ok=True, stdout=f"wrote {path}")

    def read_file_handler(inputs: dict, workdir: Path) -> ToolResult:
        path = confined_path(workdir, inputs["path"])
        if not path.exists():
            return ToolResult(
                tool="read_file", ok=False, exit_code=1, stderr=f"missing {path}"
            )
        # Only the trailing 8000 chars are returned; avoid loading very large
        # files into memory just to slice their tail.
        if path.stat().st_size > _READ_FILE_TAIL_BYTES:
            with path.open("rb") as fh:
                fh.seek(-_READ_FILE_TAIL_BYTES, 2)
                tail = fh.read().decode("utf-8", errors="replace")
            return ToolResult(tool="read_file", ok=True, stdout=tail[-8000:])
        return ToolResult(tool="read_file", ok=True, stdout=path.read_text()[-8000:])

    def grep_handler(inputs: dict, workdir: Path) -> ToolResult:
        pattern = str(inputs.get("pattern", ""))
        path = confined_path(workdir, inputs.get("path", "."))
        root = workdir.resolve()
        # Read-only search is implemented in-process, so it does not create a
        # host subprocess escape hatch in the production tool runtime. Oversized
        # and binary files are skipped: scanning vendored bundles or blobs fully
        # dominated the tool's latency and could never yield readable matches.
        matches: list[str] = []
        try:
            for candidate in path.rglob("*"):
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(root)
                except ValueError:
                    continue
                try:
                    if resolved.stat().st_size > _GREP_MAX_FILE_BYTES:
                        continue
                    with resolved.open("rb") as fh:
                        if b"\0" in fh.read(4096):
                            continue
                    for line_no, line in enumerate(
                        resolved.read_text(errors="replace").splitlines(), 1
                    ):
                        if pattern in line:
                            matches.append(f"{candidate}:{line_no}:{line}")
                except OSError:
                    continue
        except OSError as exc:
            return ToolResult(tool="grep", ok=False, exit_code=2, stderr=str(exc))
        return ToolResult(
            tool="grep",
            ok=True,
            exit_code=0 if matches else 1,
            stdout="\n".join(matches)[-8000:],
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
