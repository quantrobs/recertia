from __future__ import annotations

from pathlib import Path

from recertia.jobs.workers import practice_from_fail_clusters, practice_from_one_offs
from recertia.memory.episodic import CaseRecord, DeadEnd, EpisodicStore


def _dead(store: EpisodicStore, *, run_id: str, session_id: str, case_id: str) -> None:
    store.write(
        CaseRecord(
            case_id=case_id,
            run_id=run_id,
            attempt_no=1,
            task_class="repo-chore",
            request_excerpt="fail this chore",
            outcome="failed",
            failure_class="tool_error",
            dead_end=DeadEnd(approach="scratch", why_failed="uv lock failed"),
            session_id=session_id,
        )
    )


def test_practice_prefers_eligible_clusters(tmp_path: Path) -> None:
    episodic = EpisodicStore(tmp_path / "episodic")
    _dead(episodic, run_id="r1", session_id="s1", case_id="c1")
    _dead(episodic, run_id="r2", session_id="s1", case_id="c2")
    _dead(episodic, run_id="r3", session_id="s2", case_id="c3")
    rows = episodic.clusters.eligible()
    assert rows
    proposals = practice_from_fail_clusters(rows, curriculum_dir=tmp_path / "curr")
    assert proposals
    assert all(p.payload.get("source") == "fail_cluster" for p in proposals)

    empty = EpisodicStore(tmp_path / "empty").clusters.eligible()
    assert empty == []
    fallback = practice_from_one_offs(["unsolved one-off cluster"])
    assert fallback
    assert fallback[0].payload.get("source") != "fail_cluster"
