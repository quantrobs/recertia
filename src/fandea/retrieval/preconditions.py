"""Precondition evaluation for retrieval filtering (specs §5 step 3, §2.4).

A candidate failing any precondition — including an environment-fingerprint mismatch — is
**dropped**, never down-ranked.
"""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Callable

from contracts.skill import Precondition


@dataclass(frozen=True)
class ProbeEvidence:
    """Auditable result of one read-only retrieval probe."""

    probe: str
    passed: bool
    detail: str
    cost_units: int

    @property
    def reason(self) -> str:
        return f"{self.probe}:{self.detail}"


ProbeHandler = Callable[[dict[str, object], Path], tuple[bool, str]]


@dataclass(frozen=True)
class ReadOnlyProbe:
    """A registered in-process probe usable during retrieval."""

    name: str
    cost_units: int
    handler: ProbeHandler


class ProbeRegistry:
    def __init__(self) -> None:
        self._probes: dict[str, ReadOnlyProbe] = {}

    def register(self, probe: ReadOnlyProbe) -> None:
        if probe.cost_units < 1:
            raise ValueError("probe cost_units must be positive")
        if probe.name in self._probes:
            raise ValueError(f"probe {probe.name!r} is already registered")
        self._probes[probe.name] = probe

    def get(self, name: str) -> ReadOnlyProbe | None:
        return self._probes.get(name)


def default_probe_registry() -> ProbeRegistry:
    registry = ProbeRegistry()
    registry.register(
        ReadOnlyProbe(
            "file_exists",
            1,
            lambda arguments, workdir: (
                (workdir / str(arguments["path"])).exists(),
                f"path={arguments['path']}",
            ),
        )
    )
    registry.register(
        ReadOnlyProbe(
            "path_glob",
            2,
            lambda arguments, workdir: (
                any(workdir.glob(str(arguments["pattern"]))),
                f"pattern={arguments['pattern']}",
            ),
        )
    )
    registry.register(
        ReadOnlyProbe(
            "env_present",
            1,
            lambda arguments, _workdir: (
                str(arguments["name"]) in os.environ,
                f"name={arguments['name']}",
            ),
        )
    )
    registry.register(
        ReadOnlyProbe(
            "tool_available",
            1,
            lambda arguments, _workdir: (
                which(str(arguments["name"])) is not None,
                f"name={arguments['name']}",
            ),
        )
    )
    registry.register(
        ReadOnlyProbe(
            "python_module_available",
            1,
            lambda arguments, _workdir: (
                importlib.util.find_spec(str(arguments["module"])) is not None,
                f"module={arguments['module']}",
            ),
        )
    )
    return registry


DEFAULT_PROBES = default_probe_registry()


def _probe_request(pre: Precondition) -> tuple[str, dict[str, object]]:
    if pre.kind == "probe":
        return pre.value, pre.arguments
    argument_name = {
        "file_exists": "path",
        "path_glob": "pattern",
        "env_present": "name",
        "tool_available": "name",
    }[pre.kind]
    return pre.kind, {argument_name: pre.value}


def evaluate_precondition(
    pre: Precondition,
    workdir: Path,
    *,
    registry: ProbeRegistry = DEFAULT_PROBES,
    remaining_budget: int,
) -> ProbeEvidence:
    """Evaluate one registered read-only probe without spawning a subprocess."""

    name, arguments = _probe_request(pre)
    probe = registry.get(name)
    if probe is None:
        return ProbeEvidence(name, False, "unregistered", 0)
    if probe.cost_units > remaining_budget:
        return ProbeEvidence(name, False, f"budget_exhausted:need={probe.cost_units}", 0)
    try:
        passed, detail = probe.handler(arguments, workdir)
    except (KeyError, OSError, ValueError) as exc:
        return ProbeEvidence(name, False, f"error={exc}", probe.cost_units)
    return ProbeEvidence(name, passed, detail, probe.cost_units)


def evaluate_all(
    preconditions: list[Precondition],
    workdir: Path,
    *,
    budget_units: int = 32,
    registry: ProbeRegistry = DEFAULT_PROBES,
) -> tuple[bool, list[ProbeEvidence]]:
    """Evaluate probes within a bounded budget and retain their evidence."""

    evidence: list[ProbeEvidence] = []
    remaining_budget = budget_units
    for pre in preconditions:
        result = evaluate_precondition(
            pre, workdir, registry=registry, remaining_budget=remaining_budget
        )
        evidence.append(result)
        remaining_budget -= result.cost_units
        if not result.passed:
            return False, evidence
    return True, evidence


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
