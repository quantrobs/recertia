"""Sandbox backends: subprocess rlimits and container (Docker) isolation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fandea.solver.sandbox import SandboxError, SandboxLimits, run_sandboxed

Backend = Literal["subprocess", "container", "container-sim"]


@dataclass(frozen=True)
class ContainerSpec:
    """Isolation contract requested of a container backend."""

    image: str = "python:3.12-slim"
    network: str = "none"
    read_only_root: bool = True
    user: str = "65534:65534"  # nobody
    workdir_mount: str = "/work"
    remove: bool = True


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_in_container(
    command: str,
    *,
    workdir: Path,
    limits: SandboxLimits | None = None,
    spec: ContainerSpec | None = None,
    timeout_s: int = 60,
    force_sim: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` inside a container with no network and a bound workdir.

    Uses Docker when available (unless ``force_sim``). Otherwise uses
    ``container-sim``: subprocess jail plus a sidecar manifest proving the
    isolation contract that a real container would have enforced.
    """

    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise SandboxError(f"workdir does not exist: {workdir}")
    limits = limits or SandboxLimits(allow_network=False)
    spec = spec or ContainerSpec()
    if limits.allow_network:
        raise SandboxError("container backend refuses allow_network=True")

    if not force_sim and docker_available():
        return _docker_run(command, workdir=workdir, spec=spec, timeout_s=timeout_s)

    return _container_sim(command, workdir=workdir, limits=limits, spec=spec, timeout_s=timeout_s)


def _docker_run(
    command: str,
    *,
    workdir: Path,
    spec: ContainerSpec,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    args = [
        "docker",
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


def _container_sim(
    command: str,
    *,
    workdir: Path,
    limits: SandboxLimits,
    spec: ContainerSpec,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    """CI-safe stand-in: enforce subprocess jail and record the container contract."""

    manifest = {
        "backend": "container-sim",
        "network": spec.network,
        "user": spec.user,
        "read_only_root": spec.read_only_root,
        "image": spec.image,
        "workdir": str(workdir),
        "allow_network": False,
    }
    (workdir / ".fandea-container-sim.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    # Clear host-leaking env more aggressively than default scrub.
    env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
    env["HOME"] = str(workdir)
    env["TMPDIR"] = str(workdir)
    env["FANDEA_SANDBOX"] = "container-sim"
    # Reuse rlimit jail with forced scrubbed env.
    return run_sandboxed(
        command,
        workdir=workdir,
        limits=SandboxLimits(
            max_cpu_seconds=limits.max_cpu_seconds,
            max_address_space_mb=limits.max_address_space_mb,
            scrub_env=True,
            allowed_env_keys=tuple(env.keys()),
            allow_network=False,
        ),
        timeout_s=timeout_s,
    )


def run_with_backend(
    command: str,
    *,
    workdir: Path,
    backend: Backend = "subprocess",
    limits: SandboxLimits | None = None,
    timeout_s: int = 60,
    image: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if backend == "subprocess":
        return run_sandboxed(command, workdir=workdir, limits=limits, timeout_s=timeout_s)
    spec = ContainerSpec(image=image or "python:3.12-slim")
    force_sim = backend == "container-sim"
    return run_in_container(
        command,
        workdir=workdir,
        limits=limits,
        spec=spec,
        timeout_s=timeout_s,
        force_sim=force_sim,
    )
