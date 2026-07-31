"""Precondition evaluation for retrieval filtering (specs §5 step 3, §2.4).

A candidate failing any precondition — including an environment-fingerprint mismatch — is
**dropped**, never down-ranked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from contracts.skill import Precondition


def evaluate_precondition(pre: Precondition, workdir: Path) -> tuple[bool, str]:
    """Return ``(passed, reason)``."""

    if pre.kind == "file_exists":
        ok = (workdir / pre.value).exists()
        return ok, f"file_exists:{pre.value}={'yes' if ok else 'no'}"
    if pre.kind == "path_glob":
        matches = list(workdir.glob(pre.value))
        ok = len(matches) > 0
        return ok, f"path_glob:{pre.value}={'matched' if ok else 'none'}"
    if pre.kind == "env_present":
        import os

        ok = pre.value in os.environ
        return ok, f"env_present:{pre.value}={'yes' if ok else 'no'}"
    if pre.kind == "tool_available":
        from shutil import which

        ok = which(pre.value) is not None
        return ok, f"tool_available:{pre.value}={'yes' if ok else 'no'}"
    if pre.kind == "command_succeeds":
        try:
            proc = subprocess.run(
                pre.value,
                shell=True,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            ok = proc.returncode == 0
            return ok, f"command_succeeds:exit={proc.returncode}"
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, f"command_succeeds:error={exc}"
    return False, f"unknown_precondition_kind:{pre.kind}"


def evaluate_all(preconditions: list[Precondition], workdir: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for pre in preconditions:
        ok, reason = evaluate_precondition(pre, workdir)
        reasons.append(reason)
        if not ok:
            return False, reasons
    return True, reasons


def environment_fingerprint_matches(
    skill_fingerprint: dict[str, str],
    run_fingerprint: dict[str, str],
) -> tuple[bool, str]:
    """Hard-drop on any overlapping tool whose versions disagree (specs §5).

    Tools present on only one side are ignored — the skill may not declare every tool the
    run has, and the run may not have every tool the skill was certified against if that
    tool is unused for this task. A conflict on a shared key is the drop signal.
    """

    for tool, skill_ver in skill_fingerprint.items():
        if tool in run_fingerprint and run_fingerprint[tool] != skill_ver:
            return (
                False,
                f"env_fingerprint_mismatch:{tool}:skill={skill_ver},run={run_fingerprint[tool]}",
            )
    return True, "env_fingerprint:ok"


def parse_preconditions_json(raw: str) -> list[Precondition]:
    return [Precondition.model_validate(p) for p in json.loads(raw)]
