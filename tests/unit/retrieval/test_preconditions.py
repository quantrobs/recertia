from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.skill import Precondition
from fandea.retrieval.preconditions import evaluate_all


def test_registered_probe_returns_evidence_without_spawning_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("retrieval probes must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", forbidden)
    passed, evidence = evaluate_all(
        [
            Precondition(
                kind="probe",
                value="python_module_available",
                arguments={"module": "tomllib"},
            )
        ],
        tmp_path,
        budget_units=1,
    )

    assert passed
    assert evidence[0].probe == "python_module_available"
    assert evidence[0].passed
    assert evidence[0].cost_units == 1


def test_probe_budget_hard_drops_before_invocation(tmp_path: Path) -> None:
    passed, evidence = evaluate_all(
        [Precondition(kind="path_glob", value="*.py")],
        tmp_path,
        budget_units=1,
    )

    assert not passed
    assert evidence[0].detail == "budget_exhausted:need=2"
    assert evidence[0].cost_units == 0


def test_command_succeeds_is_not_a_retrieval_precondition() -> None:
    with pytest.raises(ValidationError):
        Precondition(kind="command_succeeds", value="touch should-not-run")
