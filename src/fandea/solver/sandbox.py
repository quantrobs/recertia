"""Sandbox limits and the disabled legacy local-process executor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxLimits:
    max_cpu_seconds: int = 60
    max_address_space_mb: int = 512
    scrub_env: bool = True
    allowed_env_keys: tuple[str, ...] = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
    allow_network: bool = False  # informational for container backends


def run_sandboxed(
    command: str,
    *,
    workdir: Path,
    limits: SandboxLimits | None = None,
    timeout_s: int = 60,
) -> object:
    """Rejected legacy API kept only to give callers a clear migration error."""

    del command, workdir, limits, timeout_s
    raise SandboxError(
        "host subprocess sandbox is disabled; use fandea.solver.container.run_in_container"
    )
