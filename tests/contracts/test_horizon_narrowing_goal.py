"""The horizon-narrowing Goal still compiles, and its checks still pass on the worked run."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from contracts.goal import Goal, compile_goal

REPO = Path(__file__).resolve().parent.parent.parent
GOAL_PATH = REPO / "docs" / "architecture" / "ten-year-horizon-narrowing-goal.json"


def test_horizon_narrowing_goal_validates_and_compiled_checks_pass() -> None:
    goal = Goal.model_validate(json.loads(GOAL_PATH.read_text(encoding="utf-8")))
    assert any(d.weight >= 1.0 and d.kind != "judge" for d in goal.desired)
    criteria = compile_goal(goal)
    assert criteria
    for criterion in criteria:
        assert criterion.kind == "command"
        assert criterion.run
        proc = subprocess.run(
            criterion.run,
            shell=True,
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == criterion.expect_exit, (
            f"{criterion.id}: {criterion.run!r} exited {proc.returncode}\n"
            f"{proc.stderr}"
        )
