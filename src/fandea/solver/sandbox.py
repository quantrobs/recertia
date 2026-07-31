"""Local process jail for tool commands (cwd-bound; optional rlimits).

Container backend is selected via :class:`fandea.governance.sandbox.SandboxPolicy` but the
policy object itself lives in T3; this module only executes an already-decided policy snapshot
passed in as plain kwargs so ``fandea.nodes`` never imports governance.
"""

from __future__ import annotations

import os
import resource
import subprocess
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


def _preexec(limits: SandboxLimits) -> None:
    # Soft/hard CPU and address-space caps (POSIX). No-op failure is ignored on unsupported OS.
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.max_cpu_seconds, limits.max_cpu_seconds))
    except (ValueError, OSError):
        pass
    try:
        bytes_cap = limits.max_address_space_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
    except (ValueError, OSError, AttributeError):
        pass


def run_sandboxed(
    command: str,
    *,
    workdir: Path,
    limits: SandboxLimits | None = None,
    timeout_s: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with cwd jailed to ``workdir`` and optional rlimits."""

    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise SandboxError(f"workdir does not exist: {workdir}")
    limits = limits or SandboxLimits()
    env = None
    if limits.scrub_env:
        env = {k: v for k, v in os.environ.items() if k in limits.allowed_env_keys}
        env.setdefault("PATH", "/usr/bin:/bin")
        env.setdefault("HOME", str(workdir))
        env.setdefault("TMPDIR", str(workdir))

    return subprocess.run(
        command,
        shell=True,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        preexec_fn=lambda: _preexec(limits),
    )
