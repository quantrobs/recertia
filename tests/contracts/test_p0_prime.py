"""P0′ contract delta: SkillStats diversity, cluster rows, job quota, lint hash."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.cluster import FailureClusterRow
from contracts.examples import bump_python_dep_stats, bump_python_dep_version
from contracts.graph import NODES
from contracts.guide import ExecutionGuide
from contracts.lint import lint_content_hash
from contracts.policy import JobQuota
from contracts.stats import ApplyDiversity, SkillStats


def test_topology_still_fifteen_nodes() -> None:
    assert len(NODES) == 15
    assert "align_skills" not in NODES


def test_apply_diversity_dedups_and_drops_sample_at_floor() -> None:
    div = ApplyDiversity(floor=3)
    div = div.note("s1").note("s1").note("s2").note("s3")
    assert div.distinct_apply_sessions == 3
    assert div.apply_session_sample == []
    # Further notes do not grow past a dropped sample.
    again = div.note("s4")
    assert again.distinct_apply_sessions == 3


def test_skill_stats_canonical_example_carries_apply_diversity() -> None:
    stats = bump_python_dep_stats()
    assert stats.apply_diversity.distinct_apply_sessions >= 2
    SkillStats.model_validate(stats.model_dump())


def test_cluster_row_becomes_eligible_at_thresholds() -> None:
    now = datetime.now(timezone.utc)
    row = FailureClusterRow(task_class="repo-chore", signature="execution::boom")
    assert row.eligible is False
    row = row.note(run_id="r1", session_id="a", case_hash="h1", at=now)
    row = row.note(run_id="r2", session_id="a", case_hash="h2", at=now)
    row = row.note(run_id="r3", session_id="a", case_hash="h3", at=now)
    assert row.n_runs == 3
    assert row.n_sessions == 1
    assert row.eligible is False
    row = row.note(run_id="r4", session_id="b", case_hash="h4", at=now)
    assert row.eligible is True


def test_job_quota_hex_is_leftover_only() -> None:
    quota = JobQuota(weekly_token_cap=1000, hex_share=0.25)
    assert quota.can_admit("recertifier", tokens=100)
    assert quota.can_admit("practice_hex", tokens=200)
    quota = quota.charge("recertifier", 900)
    assert quota.can_admit("practice_hex", tokens=200) is False
    assert quota.can_admit("fail_cluster_author", tokens=50) is True
    quota = JobQuota(weekly_token_cap=10_000, hex_share=0.25, max_hex_jobs_per_task_class=1)
    quota = quota.charge("practice_hex", 10, task_class="repo-chore")
    assert quota.can_admit("practice_hex", task_class="repo-chore") is False
    assert quota.can_admit("practice_hex", task_class="other") is True


def test_lint_content_hash_stable_and_ignores_hygiene() -> None:
    version = bump_python_dep_version()
    first = lint_content_hash(version)
    dirtied = version.model_copy(
        update={"hygiene": version.hygiene.model_copy(update={"lint_content_hash": "abc"})}
    )
    assert lint_content_hash(dirtied) == first


def test_execution_guide_is_frozen() -> None:
    guide = ExecutionGuide(
        primary=["a@v1"],
        adapted_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    with pytest.raises(Exception):
        guide.primary = ["nope"]  # type: ignore[misc]
