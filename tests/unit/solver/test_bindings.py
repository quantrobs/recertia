"""Unit tests for parameter/input binding helpers."""

from __future__ import annotations

import pytest

from contracts.resources import ResourceClaim
from contracts.skill import InputBinding, Step
from fandea.solver.apply import bind_inputs as apply_bind_inputs
from fandea.solver.bindings import (
    bind_inputs,
    bind_parameters,
    claims_conflict,
    topological_waves,
)


def test_bind_parameters_replaces_known_placeholders() -> None:
    assert bind_parameters("echo {{name}}", {"name": "hi"}) == "echo hi"
    assert bind_parameters("{{ missing }}", {}) == "{{ missing }}"


def test_bind_inputs_applies_params_and_step_bindings() -> None:
    inputs = {"command": "echo {{msg}}", "extra": 1}
    out = bind_inputs(
        inputs,
        {"msg": "ok"},
        bindings=[InputBinding(input="x", source_step="a", output="stdout")],
        step_outputs={("a", "stdout"): "prev"},
    )
    assert out == {"command": "echo ok", "extra": 1, "x": "prev"}
    # Compatibility re-export from apply.py
    assert apply_bind_inputs({"cmd": "{{a}}"}, {"a": "1"}) == {"cmd": "1"}


def test_bind_inputs_missing_output_raises() -> None:
    with pytest.raises(ValueError, match="missing bound output"):
        bind_inputs(
            {},
            {},
            bindings=[InputBinding(input="x", source_step="a", output="stdout")],
            step_outputs={},
        )


def test_topological_waves_orders_dependencies() -> None:
    steps = [
        Step(id="a", tool="shell", intent="first step here", inputs={"command": "true"}),
        Step(
            id="b",
            tool="shell",
            intent="depends on a step",
            inputs={"command": "true"},
            input_bindings=[InputBinding(input="x", source_step="a", output="stdout")],
        ),
        Step(id="c", tool="shell", intent="independent step", inputs={"command": "true"}),
    ]
    waves = topological_waves(steps, max_parallel=2)
    flat = [s.id for w in waves for s in w]
    assert flat.index("a") < flat.index("b")
    assert set(flat) == {"a", "b", "c"}
    assert all(len(w) <= 2 for w in waves)


def test_claims_conflict_write_vs_read() -> None:
    write = [ResourceClaim(kind="file", id="x", mode="write")]
    read = [ResourceClaim(kind="file", id="x", mode="read")]
    other = [ResourceClaim(kind="file", id="y", mode="write")]
    assert claims_conflict(write, read) is True
    assert claims_conflict(read, read) is False
    assert claims_conflict(write, other) is False
