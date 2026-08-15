from __future__ import annotations

import pytest

from contracts.criteria import TaskCriterion, mint_rejecting_proof


@pytest.fixture
def proven_criterion() -> TaskCriterion:
    """A required criterion with a valid sensitivity proof — genuinely gates routing."""

    base = TaskCriterion(
        id="output-exists",
        kind="command",
        run="test -f output.txt",
        source="caller",
        weight=1.0,
    )
    return base.model_copy(
        update={
            "sensitivity_proof": mint_rejecting_proof(
                base,
                negative_fixture="empty workspace",
                fingerprint="e2e-proven",
            )
        }
    )


@pytest.fixture
def unproven_required_criterion() -> TaskCriterion:
    """Required (weight=1.0) but has no sensitivity proof at all — must be advisory (specs §15.2)."""

    return TaskCriterion(
        id="impossible",
        kind="command",
        run="test -f this-file-will-never-exist.txt",
        source="caller",
        weight=1.0,
    )
