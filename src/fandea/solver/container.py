"""Production command sandbox backed exclusively by Docker or Podman."""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fandea.solver.sandbox import SandboxError, SandboxLimits

Backend = Literal["container", "local"]


@dataclass(frozen=True)
class LocalExecutionCapability:
    """Explicit opt-in for the non-production executor (tests and local development)."""

    purpose: str = "test-or-local-development"


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


def configured_backend() -> Backend:
    """Read the explicitly configured execution mode; production defaults to OCI."""

    backend = os.environ.get("FANDEA_EXECUTION_BACKEND", "container")
    if backend not in {"container", "local"}:
        raise SandboxError(f"unsupported execution backend: {backend!r}")
    return backend  # type: ignore[return-value]


def local_execution_capability() -> LocalExecutionCapability | None:
    """Grant local execution only after an explicit configuration opt-in."""

    return LocalExecutionCapability() if configured_backend() == "local" else None


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
    spec = _enforce_container_policy(spec or ContainerSpec())
    if limits.allow_network:
        raise SandboxError("container backend refuses allow_network=True")

    runtime = container_runtime()
    if runtime is None:
        raise SandboxError("no approved container runtime available (Docker or Podman required)")
    return _container_run(runtime, command, workdir=workdir, spec=spec, timeout_s=timeout_s)


_ALLOWED_IMAGES = frozenset({"python:3.12-slim", "python:3.11-slim", "python:3.12", "python:3.11"})


def _enforce_container_policy(spec: ContainerSpec) -> ContainerSpec:
    """Normalize caller-supplied specs to the immutable sandbox policy."""

    if spec.network != "none":
        raise SandboxError(f"container network {spec.network!r} is not allowed")
    if spec.user in {"0", "0:0", "root", "root:root"}:
        raise SandboxError("container root user is not allowed")
    if not spec.read_only_root:
        raise SandboxError("writable container root filesystem is not allowed")
    if not spec.workdir_mount.startswith("/"):
        raise SandboxError("workdir_mount must be an absolute container path")
    if spec.image not in _ALLOWED_IMAGES and not os.environ.get("FANDEA_ALLOW_CUSTOM_IMAGE"):
        raise SandboxError(f"container image {spec.image!r} is not on the allowlist")
    return spec


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
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
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
    local_capability: LocalExecutionCapability | None = None,
) -> subprocess.CompletedProcess[str]:
    if backend == "local":
        if local_capability is None:
            raise SandboxError("local execution requires an explicit LocalExecutionCapability")
        return _local_run(command, workdir=workdir, limits=limits or SandboxLimits(), timeout_s=timeout_s)
    if backend != "container":
        raise SandboxError(f"unsupported execution backend: {backend!r}")
    spec = ContainerSpec(image=image or "python:3.12-slim")
    return run_in_container(
        command,
        workdir=workdir,
        limits=limits,
        spec=spec,
        timeout_s=timeout_s,
    )


def run_configured_command(
    command: str,
    *,
    workdir: Path,
    limits: SandboxLimits | None = None,
    timeout_s: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run via OCI by default, or the explicitly opted-in local capability."""

    backend = configured_backend()
    return run_with_backend(
        command,
        workdir=workdir,
        backend=backend,
        limits=limits,
        timeout_s=timeout_s,
        local_capability=local_execution_capability(),
    )


def _local_run(
    command: str, *, workdir: Path, limits: SandboxLimits, timeout_s: int
) -> subprocess.CompletedProcess[str]:
    """Bounded local executor for explicitly opted-in test/development use only."""

    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise SandboxError(f"workdir does not exist: {workdir}")
    env = {key: value for key, value in os.environ.items() if key in limits.allowed_env_keys}
    env.setdefault("PATH", "/usr/bin:/bin")
    env.setdefault("HOME", str(workdir))
    env.setdefault("TMPDIR", str(workdir))

    def limit_process() -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.max_cpu_seconds, limits.max_cpu_seconds))
            bytes_cap = limits.max_address_space_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
        except (AttributeError, OSError, ValueError):
            pass

    return subprocess.run(
        command,
        shell=True,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        preexec_fn=limit_process,
    )
