from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.criteria import SensitivityProof, TaskCriterion


@pytest.fixture
def proven_criterion() -> TaskCriterion:
    """A required criterion with a valid sensitivity proof — genuinely gates routing."""

    return TaskCriterion(
        id="output-exists",
        kind="command",
        run="test -f output.txt",
        source="caller",
        weight=1.0,
        sensitivity_proof=SensitivityProof(
            criterion_id="output-exists",
            negative_fixture="empty workspace",
            rejected=True,
            checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
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
