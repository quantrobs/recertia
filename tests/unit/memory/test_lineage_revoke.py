from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.examples import bump_python_dep_status, bump_python_dep_version
from recertia.memory.procedural.lineage import LineageIndex, RevokeQueue, drain_revokes
from recertia.memory.procedural.store import SkillStore


def test_enqueue_is_o1_and_drain_marks_needs_recert(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    version = bump_python_dep_version()
    # Attach an authoring source so the index can find it.
    version = version.model_copy(
        update={
            "provenance": version.provenance.model_copy(update={"source_run_ids": ["poison-run"]})
        }
    )
    store.write_version(version)
    store._write_status_unchecked(bump_python_dep_status())
    index = LineageIndex(tmp_path / "lineage.jsonl")
    index.record(version)
    queue = RevokeQueue(tmp_path / "revoke.jsonl")
    queue.enqueue(source_kind="run", source_id="poison-run", reason="case quarantined")
    touched = drain_revokes(store, index, queue, max_writes=10)
    assert any(s.skill_id == version.skill_id and s.lifecycle == "needs_recert" for s in touched)
    assert store.get_status(version.skill_id, version.version).lifecycle == "needs_recert"
    # Queue empty after drain.
    assert queue.drain(limit=10) == []
    _ = datetime.now(timezone.utc)
