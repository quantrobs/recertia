"""S1: step edges are declared only by typed output bindings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts.examples import bump_python_dep_version
from contracts.skill import Step, step_dependencies


def test_canonical_step_edges_are_derived_from_input_bindings() -> None:
    version = bump_python_dep_version()
    steps = {step.id: step for step in version.steps}

    assert step_dependencies(steps["edit"]) == {"locate"}
    assert step_dependencies(steps["repair"]) == {"sync", "changelog"}


def test_free_floating_depends_on_is_rejected() -> None:
    with pytest.raises(ValidationError, match="depends_on"):
        Step(id="consumer", intent="Consume a producer output.", depends_on=["producer"])  # type: ignore[call-arg]


def test_binding_must_reference_a_declared_source_output() -> None:
    data = bump_python_dep_version().model_dump(mode="json")
    data["steps"][2]["input_bindings"][0]["output"] = "not_declared"

    with pytest.raises(ValidationError, match="unknown output"):
        type(bump_python_dep_version()).model_validate(data)
