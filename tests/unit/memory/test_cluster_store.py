from __future__ import annotations

from pathlib import Path

from recertia.memory.episodic import CaseRecord, DeadEnd, EpisodicStore
from recertia.memory.episodic.clusters import normalize_signature


def test_dead_end_write_upserts_cluster_incrementally(tmp_path: Path) -> None:
    episodic = EpisodicStore(tmp_path / "episodic")
    why = "shell exit 1 on missing marker"
    for i in range(3):
        episodic.write(
            CaseRecord(
                case_id=f"c{i}",
                run_id=f"run-{i}",
                attempt_no=1,
                task_class="repo-chore",
                outcome="failed",
                failure_class="execution",
                session_id=f"sess-{i}",
                dead_end=DeadEnd(approach="scratch", why_failed=why),
            )
        )
    sig = normalize_signature(why, "execution")
    row = episodic.clusters.get("repo-chore", sig)
    assert row is not None
    assert row.n_runs == 3
    assert row.n_sessions == 3
    assert row.eligible is True
    eligible = episodic.clusters.eligible(task_class="repo-chore")
    assert len(eligible) == 1
    assert eligible[0].signature == sig
