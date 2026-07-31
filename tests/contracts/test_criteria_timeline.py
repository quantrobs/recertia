"""B2 / ADR-0003 amendment: TaskCriterion and SkillCertificationCriterion never merge."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.criteria import SkillCertificationCriterion, TaskCriterion
from contracts.run import RunManifest, RunState, Task

_NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


def test_run_state_criteria_field_only_accepts_task_criterion():
    with pytest.raises(ValidationError):
        RunState(
            run_id="run-1",
            task=Task(task_id="t1", request="do it", submitted_at=_NOW),
            manifest=RunManifest(),
            criteria=[
                SkillCertificationCriterion(id="c1", kind="command", run="pytest -q"),
            ],
        )


def test_task_criterion_source_excludes_skill_selection():
    # A skill is never a valid source for a locked TaskCriterion — plan has not run at intake.
    with pytest.raises(ValidationError):
        TaskCriterion(id="c1", kind="command", run="pytest -q", source="skill")


def test_task_criterion_accepts_caller_task_class_or_critic():
    for source in ("caller", "task_class_template", "critic"):
        TaskCriterion(id="c1", kind="command", run="pytest -q", source=source)


def test_certification_criterion_preregistered_defaults_false_until_locked_for_cert_runs():
    criterion = SkillCertificationCriterion(id="c1", kind="command", run="pytest -q")
    assert criterion.preregistered is False


def test_a_valid_run_state_carries_only_task_criteria():
    state = RunState(
        run_id="run-1",
        task=Task(task_id="t1", request="do it", submitted_at=_NOW),
        manifest=RunManifest(criteria_hash="abc"),
        criteria_locked_at=_NOW,
        criteria=[TaskCriterion(id="c1", kind="command", run="pytest -q", source="caller")],
    )
    assert all(isinstance(c, TaskCriterion) for c in state.criteria)
    assert state.certification_observations == []
