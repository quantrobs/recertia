"""Behavioral regression tests for the performance refactor.

Each test pins the externally visible contract of an optimization: caches must
invalidate on external change, incremental index paths must match full rebuilds,
and the differential restore must still produce an exact mirror.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import CriterionResult, TaskCriterion
from contracts.fact import Fact, FactProvenance
from contracts.resources import ResourceClaim
from contracts.run import RunManifest, RunState, SkillCandidateRef, Task
from recertia.bootstrap import build_default_orchestrator
from recertia.evals.store import EvalStore
from recertia.ledger import HashChainLedger
from recertia.memory.episodic import CaseRecord, EpisodicStore
from recertia.memory.procedural.seeds import (
    add_gitignore_entry,
    add_pytest_config,
    seed_approved_for_tests,
)
from recertia.memory.procedural.store import SkillStore
from recertia.memory.semantic import FactStore
from recertia.retrieval.index import SkillIndex, embed_text
from recertia.retrieval.pipeline import Retriever
from recertia.solver.claims import ClaimScheduler
from recertia.solver.tools import ToolRuntime, default_registry
from recertia.workspace import WorkspaceManager


def _fact(fact_id: str, slug: str, assertion: str, confidence: float) -> Fact:
    return Fact(
        fact_id=fact_id,
        scope="project",
        slug=slug,
        assertion=assertion,
        confidence=confidence,
        provenance=FactProvenance(asserting_run="test"),
        authored_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Ledger: cached tip with file-stat invalidation
# ---------------------------------------------------------------------------


def test_ledger_append_notices_external_appends(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    first = HashChainLedger(path)
    second = HashChainLedger(path)

    e0 = first.append(actor="a", action="write", target="t0")
    assert e0.seq == 0
    e1 = second.append(actor="b", action="write", target="t1")
    assert e1.seq == 1
    # The first instance's cached tip is stale here; the stat check must force a rescan.
    e2 = first.append(actor="a", action="write", target="t2")
    assert e2.seq == 2
    assert e2.prev_hash == e1.entry_hash
    first.verify()
    second.verify()


def test_ledger_tip_hash_tracks_appends(tmp_path: Path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    entry = ledger.append(actor="a", action="write", target="t")
    assert ledger.tip_hash() == entry.entry_hash


# ---------------------------------------------------------------------------
# SkillIndex: freshness, upsert, batch fetch, precomputed query embeddings
# ---------------------------------------------------------------------------


def _seeded_store(root: Path) -> tuple[SkillStore, list]:
    store = SkillStore(root)
    version = add_pytest_config()
    seed_approved_for_tests(store, version, active=True)
    return store, store.iter_loaded()


def test_index_freshness_round_trip(tmp_path: Path) -> None:
    store, entries = _seeded_store(tmp_path / "skills")
    index = SkillIndex(tmp_path / "idx.db")
    fingerprint = store.library_fingerprint()
    assert not index.is_fresh(fingerprint)
    index.rebuild(entries, library_fingerprint=fingerprint)
    assert index.is_fresh(fingerprint)

    seed_approved_for_tests(store, add_gitignore_entry(), active=True)
    assert not index.is_fresh(store.library_fingerprint())
    index.close()


def test_index_upsert_matches_full_rebuild_for_search(tmp_path: Path) -> None:
    store, entries = _seeded_store(tmp_path / "skills")
    index = SkillIndex(tmp_path / "idx.db")
    index.rebuild(entries, library_fingerprint=store.library_fingerprint())

    new_version = add_gitignore_entry()
    seed_approved_for_tests(store, new_version, active=True)
    status = store.get_status(new_version.skill_id, new_version.version)
    stats = store.get_stats(new_version.skill_id, new_version.version)
    snap_after_upsert = index.upsert(
        new_version, status, stats, library_fingerprint=store.library_fingerprint()
    )

    fresh = SkillIndex(tmp_path / "fresh.db")
    snap_after_rebuild = fresh.rebuild(store.iter_loaded())
    assert snap_after_upsert == snap_after_rebuild

    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / ".gitignore").write_text("")
    bundle, _ = Retriever(index).search("add a gitignore entry", workdir=workdir)
    assert any(c.skill_id == "add-gitignore-entry" for c in bundle.skills)
    index.close()
    fresh.close()


def test_index_get_rows_matches_get_row(tmp_path: Path) -> None:
    _store, entries = _seeded_store(tmp_path / "skills")
    index = SkillIndex(tmp_path / "idx.db")
    index.rebuild(entries)
    keys = [(v.skill_id, v.version) for v, _s, _st in entries]
    rows = index.get_rows(keys)
    assert set(rows) == set(keys)
    for key in keys:
        assert rows[key] == index.get_row(*key)
    index.close()


def test_vector_top_k_accepts_precomputed_query_embedding(tmp_path: Path) -> None:
    _store, entries = _seeded_store(tmp_path / "skills")
    index = SkillIndex(tmp_path / "idx.db")
    index.rebuild(entries)
    query = "pytest configuration"
    assert index.vector_top_k(query, 3) == index.vector_top_k(query, 3, q_emb=embed_text(query))
    index.close()


def test_embed_text_is_deterministic_and_normalised() -> None:
    a = embed_text("add pytest config to the repo")
    b = embed_text("add pytest config to the repo")
    assert a == b
    assert abs(sum(v * v for v in a) ** 0.5 - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Bootstrap: fresh libraries skip the rebuild
# ---------------------------------------------------------------------------


def test_second_bootstrap_skips_index_rebuild(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    facts_root = tmp_path / "facts"
    seed_approved_for_tests(SkillStore(skills_root), add_pytest_config(), active=True)

    first = build_default_orchestrator(
        tmp_path / "runs", skills_root=skills_root, facts_root=facts_root
    )
    first.close()

    calls = 0
    original = SkillIndex.rebuild

    def counting_rebuild(self, entries, *, library_fingerprint=None):
        nonlocal calls
        calls += 1
        return original(self, entries, library_fingerprint=library_fingerprint)

    try:
        SkillIndex.rebuild = counting_rebuild  # type: ignore[method-assign]
        second = build_default_orchestrator(
            tmp_path / "runs", skills_root=skills_root, facts_root=facts_root
        )
        second.close()
    finally:
        SkillIndex.rebuild = original  # type: ignore[method-assign]
    assert calls == 0


# ---------------------------------------------------------------------------
# Workspace: differential restore still produces an exact mirror
# ---------------------------------------------------------------------------


def test_restore_rewrites_only_what_changed(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    untouched = workdir / "untouched.txt"
    untouched.write_text("keep me")
    changed = workdir / "changed.txt"
    changed.write_text("original")
    deleted = workdir / "deleted.txt"
    deleted.write_text("will be removed then restored")

    mgr = WorkspaceManager(tmp_path / "snapshots")
    ref = mgr.snapshot(workdir, run_id="r1", attempt_no=0)
    untouched_ino = untouched.stat().st_ino

    changed.write_text("mutated")
    stale = workdir / "stale.txt"
    stale.write_text("not in snapshot")
    deleted.unlink()

    mgr.restore(workdir, ref)

    assert changed.read_text() == "original"
    assert not stale.exists()
    assert deleted.read_text() == "will be removed then restored"
    # The differential restore must not rewrite files the attempt left alone.
    assert untouched.stat().st_ino == untouched_ino


def test_restore_into_missing_workdir_full_copies(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "a.txt").write_text("a")
    mgr = WorkspaceManager(tmp_path / "snapshots")
    ref = mgr.snapshot(workdir, run_id="r1", attempt_no=0)

    import shutil

    shutil.rmtree(workdir)
    mgr.restore(workdir, ref)
    assert (workdir / "a.txt").read_text() == "a"


# ---------------------------------------------------------------------------
# Episodic / semantic caches: invalidate on internal and external writes
# ---------------------------------------------------------------------------


def _case(case_id: str) -> CaseRecord:
    return CaseRecord(
        case_id=case_id,
        run_id="r",
        attempt_no=1,
        task_class="repo-chore",
        outcome="failed",
    )


def test_episodic_index_cache_tracks_writes_and_external_appends(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "episodic")
    store.write(_case("c1"))
    assert [r["case_id"] for r in store.list_index()] == ["c1"]
    # Warm the cache, then append behind the store's back.
    store.list_index()
    with store.index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"case_id": "external", "hash": "x", "run_id": "r"}) + "\n")
    assert [r["case_id"] for r in store.list_index()] == ["c1", "external"]


def test_fact_retrieve_reflects_writes_and_external_files(tmp_path: Path) -> None:
    store = FactStore(tmp_path / "facts")
    store.write(_fact("f1", "uses-pytest", "This repository uses pytest for testing", 0.9))
    assert [f.fact_id for f in store.retrieve("pytest", scope="project")] == ["f1"]

    external = _fact("f2", "uses-ruff", "This repository uses ruff for linting", 0.8)
    (tmp_path / "facts" / "project" / "uses-ruff.json").write_text(
        external.model_dump_json(), encoding="utf-8"
    )
    ids = {f.fact_id for f in store.retrieve("ruff", scope="project")}
    assert "f2" in ids


# ---------------------------------------------------------------------------
# Eval store: bulk contribution samples match the per-skill queries
# ---------------------------------------------------------------------------


def _observed_state(run_id: str, *, arm: str, chosen=False, suppressed=False) -> RunState:
    criterion = TaskCriterion(id="req", kind="command", run="true", source="caller")
    return RunState(
        run_id=run_id,
        task=Task(
            task_id=run_id,
            request="do the chore",
            task_class="repo-chore",
            submitted_at=datetime.now(timezone.utc),
        ),
        manifest=RunManifest(index_snapshot_id="snap", criteria_hash="locked"),
        arm=arm,  # type: ignore[arg-type]
        criteria=[criterion],
        criteria_locked_at=datetime.now(timezone.utc),
        chosen=SkillCandidateRef(skill_id="sk", version=1, score=1.0) if chosen else None,
        suppressed_skill=(
            SkillCandidateRef(skill_id="sk", version=1, score=1.0) if suppressed else None
        ),
        attempt_no=1,
        results=[CriterionResult(criterion_id="req", kind="command", passed=True)],
        terminal="solved",
    )


def test_contribution_samples_bulk_matches_per_skill(tmp_path: Path) -> None:
    store = EvalStore(tmp_path / "evals.sqlite")
    store.append_run(_observed_state("shadow-1", arm="shadow", chosen=True))
    store.append_run(_observed_state("supp-1", arm="control", suppressed=True))

    per_skill = store.contribution_samples(skill_id="sk", version=1, task_class="repo-chore")
    bulk = store.contribution_samples_bulk(task_class="repo-chore")
    assert bulk[("sk", 1)] == per_skill
    assert ("absent", 9) not in bulk
    store.close()


# ---------------------------------------------------------------------------
# Claim scheduler: condition-based wait wakes on release
# ---------------------------------------------------------------------------


def test_claim_waiter_wakes_promptly_on_release() -> None:
    scheduler = ClaimScheduler(claim_timeout_s=10.0)
    claim = ResourceClaim(kind="file", id="shared", mode="write")
    scheduler.acquire("holder", [claim])

    acquired: list[str] = []
    started = time.monotonic()

    def waiter() -> None:
        scheduler.acquire("waiter", [claim])
        acquired.append("waiter")

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.15)
    scheduler.release("holder", [claim])
    thread.join(timeout=5)

    assert acquired == ["waiter"]
    # Well under the 10s timeout: the condition wakes the waiter on release.
    assert time.monotonic() - started < 5
    conflicts = [c for c in scheduler.conflicts if c.waiting == "waiter"]
    assert conflicts and conflicts[-1].resolution == "acquired"
    scheduler.release("waiter", [claim])


# ---------------------------------------------------------------------------
# Tool handlers: bounded reads
# ---------------------------------------------------------------------------


def test_grep_skips_oversized_and_binary_files(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "small.txt").write_text("needle in a small file\n")
    big = work / "big.txt"
    big.write_text("needle at start\n" + ("padding line\n" * 200_000))
    (work / "blob.bin").write_bytes(b"\x00\x01needle\x00")

    tools = ToolRuntime(default_registry(), require_approval_for_non_read=True)
    result = tools.invoke("grep", {"pattern": "needle", "path": "."}, workdir=work, step_id="s1")
    assert result.ok and result.exit_code == 0
    assert "small.txt" in result.stdout
    assert "big.txt" not in result.stdout
    assert "blob.bin" not in result.stdout


def test_read_file_large_file_tail(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    marker = "TAIL-MARKER-12345"
    content = "filler line\n" * 20_000 + marker + "\n"
    (work / "large.log").write_text(content)

    tools = ToolRuntime(default_registry(), require_approval_for_non_read=True)
    result = tools.invoke("read_file", {"path": "large.log"}, workdir=work, step_id="s1")
    assert result.ok
    assert marker in result.stdout
    assert len(result.stdout) <= 8000
