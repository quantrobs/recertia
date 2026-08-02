"""Tests for digest-sealed must_not_modify freezes."""

from __future__ import annotations

from pathlib import Path

from contracts.criteria import TaskCriterion
from contracts.goal import Constraint, DesiredState, Goal, compile_goal
from recertia.validation.freeze import path_digest, seal_must_not_modify_criteria


def test_seal_embeds_digest_and_changes_on_mutation(tmp_path: Path) -> None:
    (tmp_path / "frozen.txt").write_text("v1", encoding="utf-8")
    goal = Goal(
        desired=[DesiredState(id="ok", kind="file_exists", path="frozen.txt")],
        constraints=[Constraint(id="fz", kind="must_not_modify", value=["frozen.txt"])],
    )
    criteria = compile_goal(goal)
    sealed = seal_must_not_modify_criteria(criteria, goal=goal, workdir=tmp_path)
    freeze = next(c for c in sealed if c.id == "fz")
    d1 = path_digest(tmp_path, "frozen.txt")
    assert "python -c" in (freeze.run or "")
    assert d1 in (freeze.run or "")

    (tmp_path / "frozen.txt").write_text("v2", encoding="utf-8")
    d2 = path_digest(tmp_path, "frozen.txt")
    assert d1 != d2
    assert d2 not in (freeze.run or "")


def test_seal_noop_without_freeze(tmp_path: Path) -> None:
    goal = Goal(desired=[DesiredState(id="ok", kind="file_exists", path="x")])
    criteria = [TaskCriterion(id="ok", kind="command", run="true", source="caller")]
    out = seal_must_not_modify_criteria(criteria, goal=goal, workdir=tmp_path)
    assert out == criteria
