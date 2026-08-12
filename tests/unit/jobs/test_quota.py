from __future__ import annotations

from contracts.policy import JobQuota
from recertia.jobs import JobBudget, JobRunner
from recertia.memory.procedural.store import SkillStore


def test_runner_skips_hex_when_quota_exhausted(tmp_path) -> None:
    quota = JobQuota(weekly_token_cap=100, hex_share=0.25)
    quota = quota.charge("recertifier", 100)
    runner = JobRunner(SkillStore(tmp_path / "skills"), quota=quota)
    called = {"n": 0}

    def fn():
        called["n"] += 1
        return []

    result = runner.run("practice_hex", fn, budget=JobBudget(max_tokens=10))
    assert result.skipped
    assert called["n"] == 0
    result = runner.run("fail_cluster_author", fn, budget=JobBudget(max_tokens=0))
    assert result.skipped is None
    assert called["n"] == 1
