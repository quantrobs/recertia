"""Production command sandbox backed exclusively by Docker or Podman."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fandea.solver.sandbox import SandboxError, SandboxLimits

Backend = Literal["container"]


@dataclass(frozen=True)
class ContainerSpec:
    """Isolation contract requested of a container backend."""

    image: str = "python:3.12-slim"
    network: str = "none"
    read_only_root: bool = True
    user: str = "65534:65534"  # nobody
    workdir_mount: str = "/work"
    remove: bool = True


def container_runtime() -> str | None:
    """Return the explicitly requested or first approved OCI runtime."""

    requested = os.environ.get("FANDEA_CONTAINER_RUNTIME")
    if requested:
        if requested not in {"docker", "podman"}:
            return None
        return requested if shutil.which(requested) else None
    return next((runtime for runtime in ("docker", "podman") if shutil.which(runtime)), None)


def run_in_container(
    command: str,
    *,
    workdir: Path,
    limits: SandboxLimits | None = None,
    spec: ContainerSpec | None = None,
    timeout_s: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` inside a container with no network and a bound workdir.

    There is deliberately no local-process or simulated fallback.  A command
    that cannot be run in an approved OCI runtime is rejected before execution.
    """

    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise SandboxError(f"workdir does not exist: {workdir}")
    limits = limits or SandboxLimits(allow_network=False)
    spec = spec or ContainerSpec()
    if limits.allow_network:
        raise SandboxError("container backend refuses allow_network=True")

    runtime = container_runtime()
    if runtime is None:
        raise SandboxError("no approved container runtime available (Docker or Podman required)")
    return _container_run(runtime, command, workdir=workdir, spec=spec, timeout_s=timeout_s)


def _container_run(
    runtime: str,
    command: str,
    *,
    workdir: Path,
    spec: ContainerSpec,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    args = [
        runtime,
        "run",
        "--rm" if spec.remove else "",
        f"--network={spec.network}",
        f"--user={spec.user}",
        f"--workdir={spec.workdir_mount}",
        "-v",
        f"{workdir}:{spec.workdir_mount}:rw",
        "--memory",
        "512m",
        "--cpus",
        "1",
    ]
    if spec.read_only_root:
        args.append("--read-only")
        args.extend(["--tmpfs", "/tmp:rw,size=64m"])
    args = [a for a in args if a]
    args.extend([spec.image, "sh", "-c", command])
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)


def run_with_backend(
    command: str,
    *,
    workdir: Path,
    backend: Backend = "container",
    limits: SandboxLimits | None = None,
    timeout_s: int = 60,
    image: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if backend != "container":
        raise SandboxError(f"unsupported production sandbox backend: {backend!r}")
    spec = ContainerSpec(image=image or "python:3.12-slim")
    return run_in_container(
        command,
        workdir=workdir,
        limits=limits,
        spec=spec,
        timeout_s=timeout_s,
    )
