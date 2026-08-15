#!/usr/bin/env python3
"""Measure the online critical path against growing durable state.

Recertia's premise is that the memory planes get bigger over time and runs get better
because of it. That only holds if the cost of consulting memory does not grow with its
size, so this harness answers three questions with numbers instead of intuition:

1. ``retrieve`` is mandatory and federates five planes. Does its latency grow with the
   episodic history and fact library it reads? (``retrieve-scaling``)
2. A walk re-serialises ``RunState`` at every hop and the state accumulates a route entry
   per hop. What does checkpointing cost as a run gets longer? (``walk-cost``)
3. Every run start rebuilds or revalidates the procedural index. What does the library
   size cost at startup? (``startup``)

Run all of it with ``python3 scripts/bench_critical_path.py``, or one section with
``--only retrieve-scaling``. ``--json`` emits machine-readable rows for tracking over time.
Timings report the minimum of several iterations: the minimum is the least noisy estimator
of the work itself, which is what a regression would change.

This measures engine and memory overhead only. Solves are scripted and no model is wired,
so no number here includes model latency -- the point is precisely to see the overhead that
model latency would otherwise hide.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
# Prefer this checkout's sources over any editable install, so comparing two revisions
# measures the revision it was invoked from rather than whatever is installed.
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from contracts.budget import Budget  # noqa: E402
from contracts.fact import Fact, FactProvenance  # noqa: E402
from contracts.run import Artifact, RouteEntry, RunState, Task  # noqa: E402
from recertia.graph.ops import OperationLedger  # noqa: E402
from recertia.graph.store import CheckpointStore  # noqa: E402
from recertia.ledger import HashChainLedger  # noqa: E402
from recertia.memory.affordance import AffordanceStore  # noqa: E402
from recertia.memory.episodic import CaseRecord, DeadEnd, EpisodicStore  # noqa: E402
from recertia.memory.procedural.store import SkillStore  # noqa: E402
from recertia.memory.semantic import FactStore  # noqa: E402
from recertia.nodes.context import NodeContext  # noqa: E402
from recertia.nodes.retrieve import retrieve  # noqa: E402
from recertia.retrieval.index import SkillIndex  # noqa: E402
from recertia.retrieval.pipeline import Retriever  # noqa: E402
from recertia.workspace import WorkspaceManager  # noqa: E402

FIXED_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
QUERY = "add an editorconfig file to the repository"


def best_ms(fn: Callable[[], object], *, iterations: int) -> float:
    best = float("inf")
    for _ in range(iterations):
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best * 1000.0


class Reporter:
    """Collects rows so a section can print a table or emit JSON."""

    def __init__(self, *, as_json: bool) -> None:
        self.as_json = as_json
        self.rows: list[dict] = []

    def section(self, name: str, title: str, columns: Iterable[str]) -> None:
        self._section = name
        self._columns = list(columns)
        if not self.as_json:
            print(f"\n{title}")
            print("  " + "  ".join(f"{c:>16}" for c in self._columns))

    def row(self, **values: object) -> None:
        self.rows.append({"section": self._section, **values})
        if not self.as_json:
            cells = []
            for column in self._columns:
                value = values.get(column, "")
                cells.append(f"{value:>16.3f}" if isinstance(value, float) else f"{value:>16}")
            print("  " + "  ".join(cells))

    def note(self, text: str) -> None:
        if not self.as_json:
            print(f"  {text}")

    def finish(self) -> None:
        if self.as_json:
            json.dump(self.rows, sys.stdout, indent=2)
            print()


# --------------------------------------------------------------------------------------
# Fixtures: durable state at a chosen size
# --------------------------------------------------------------------------------------


def seed_episodic(store: EpisodicStore, count: int, *, task_class: str) -> None:
    """Cases from a *different* task class.

    This is the honest shape for a growing deployment: history is dominated by task classes
    other than the one running now, so a lookup that scans until it finds matches never gets
    to short-circuit. Seeding matching cases would flatter any implementation.
    """

    for i in range(count):
        solved = i % 3 == 0
        store.write(
            CaseRecord(
                case_id=f"case-{i}",
                run_id=f"run-{i}",
                attempt_no=1,
                task_class=task_class,
                outcome="solved" if solved else "failed",
                failure_class=None if solved else "tool",
                dead_end=None if solved else DeadEnd(approach=f"approach-{i}", why_failed="no"),
                recorded_at=FIXED_TIME,
            )
        )


def seed_facts(store: FactStore, count: int) -> None:
    for i in range(count):
        store.write(
            Fact(
                fact_id=f"f-{i}",
                slug=f"fact-{i}",
                scope="project",
                assertion=f"Assertion {i} about repository layout, tooling and configuration.",
                confidence=0.7,
                provenance=FactProvenance(asserting_run="bench"),
                authored_at=FIXED_TIME,
            )
        )


def bench_state(root: Path) -> RunState:
    return RunState(
        run_id="bench",
        task=Task(
            task_id="bench",
            request=QUERY,
            task_class="repo-chore",
            submitted_at=FIXED_TIME,
        ),
        budget=Budget(),
    )


def bench_context(root: Path, *, episodic: EpisodicStore, facts: FactStore) -> NodeContext:
    workdir = root / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    return NodeContext(
        run_id="bench",
        attempt_no=0,
        node="retrieve",
        workdir=workdir,
        workspaces=WorkspaceManager(root / "snapshots"),
        ledger=HashChainLedger(root / "ledger.jsonl"),
        ops=OperationLedger(root / "ops.sqlite"),
        retriever=Retriever(SkillIndex(root / "skill_index.db")),
        episodic=episodic,
        facts=facts,
        affordances=AffordanceStore(root / "affordances.json"),
    )


# --------------------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------------------


def bench_retrieve_scaling(root: Path, reporter: Reporter, *, iterations: int) -> None:
    """``retrieve`` latency as episodic history and the fact library grow."""

    reporter.section(
        "retrieve-scaling",
        "retrieve() latency vs durable state size (no model, no skills indexed)",
        ["cases", "facts", "retrieve_ms", "us_per_record"],
    )
    for cases, facts in ((0, 0), (1_000, 0), (16_000, 0), (0, 400), (0, 1_600), (16_000, 1_600)):
        base = root / f"retrieve-{cases}-{facts}"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True)
        episodic = EpisodicStore(base / "episodic")
        seed_episodic(episodic, cases, task_class="research-synthesis")
        fact_store = FactStore(base / "facts")
        seed_facts(fact_store, facts)
        ctx = bench_context(base, episodic=episodic, facts=fact_store)
        state = bench_state(base)
        elapsed = best_ms(lambda: retrieve(state, ctx), iterations=iterations)
        total = cases + facts
        reporter.row(
            cases=cases,
            facts=facts,
            retrieve_ms=elapsed,
            us_per_record=(elapsed * 1000.0 / total) if total else 0.0,
        )
    reporter.note(
        "Episodic lookups are bucketed and should stay flat. Facts are scored by scan by "
        "design (every fact carries a floor score), so they should stay linear with a small "
        "coefficient -- watch us_per_record, not the total."
    )


def bench_walk_cost(root: Path, reporter: Reporter, *, hops: int) -> None:
    """What one more hop costs, given a checkpoint carries the whole ``RunState``."""

    reporter.section(
        "walk-cost",
        f"Checkpoint cost over a {hops}-hop walk (full RunState per hop)",
        ["hop", "state_bytes", "save_ms", "cumulative_kb"],
    )
    base = root / "walk"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    store = CheckpointStore(base / "checkpoints.db")
    state = bench_state(base)
    cumulative = 0
    sampled = {1, hops // 4, hops // 2, hops}
    for hop in range(1, hops + 1):
        # Each hop appends a route entry, and solve attempts append artifacts; both are the
        # growth the per-hop full-state serialisation has to carry.
        state = state.model_copy(
            update={
                "route_log": [
                    *state.route_log,
                    RouteEntry(
                        node="solve",
                        route="attempt_completed",
                        reason="scripted attempt completed without failure signal",
                        attempt_no=hop,
                        at=FIXED_TIME,
                    ),
                ],
                "artifacts": [
                    *state.artifacts,
                    Artifact(kind="text", ref=f"artifact-{hop}", description="written by solve"),
                ],
            }
        )
        payload_bytes = len(state.model_dump_json())
        cumulative += payload_bytes
        elapsed = best_ms(
            lambda: store.save("bench", hop, "solve", "validate", state), iterations=3
        )
        if hop in sampled:
            reporter.row(
                hop=hop,
                state_bytes=payload_bytes,
                save_ms=elapsed,
                cumulative_kb=cumulative / 1024.0,
            )
    reporter.note(
        "Bytes written over a walk grow with the square of its length: hop N re-writes "
        "everything the first N-1 hops accumulated. Fine at chore length, and the reason "
        "long multi-evolve runs deserve a delta checkpoint before they get longer."
    )


def bench_startup(root: Path, reporter: Reporter, *, iterations: int) -> None:
    """Per-run startup work that scales with the procedural library."""

    from contracts.status import Certification
    from recertia.memory.procedural.seeds import seed_approved_for_tests

    reporter.section(
        "startup",
        "Per-run startup work vs procedural library size",
        ["skills", "fingerprint_ms", "rebuild_ms", "upsert_ms"],
    )
    for count in (10, 100, 400):
        base = root / f"library-{count}"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True)
        skills = SkillStore(base / "skills")
        for i in range(count):
            seed_approved_for_tests(
                skills,
                _bench_skill(i),
                active=True,
                certification=Certification(
                    model_validated_on="bench", tool_fingerprint={}, recert_status="fresh"
                ),
            )
        fingerprint_ms = best_ms(skills.library_fingerprint, iterations=iterations)
        index = SkillIndex(base / "skill_index.db")
        entries = skills.iter_loaded()
        rebuild_ms = best_ms(
            lambda: index.rebuild(entries, library_fingerprint="bench"), iterations=1
        )
        version, status, stats = entries[0]
        upsert_ms = best_ms(lambda: index.upsert(version, status, stats), iterations=iterations)
        reporter.row(
            skills=count,
            fingerprint_ms=fingerprint_ms,
            rebuild_ms=rebuild_ms,
            upsert_ms=upsert_ms,
        )
        index.close()
    reporter.note(
        "fingerprint_ms is paid by every run start and every API process that wires an "
        "orchestrator; rebuild_ms only when the library changed underneath the index. "
        "upsert_ms is one new candidate at store time -- it recomputes the snapshot id over "
        "the whole library, which is why it tracks library size."
    )


def _bench_skill(index: int):
    from contracts.criteria import SensitivityProof, SkillCertificationCriterion
    from contracts.skill import Hygiene, Provenance, SkillVersion, Step

    return SkillVersion(
        skill_id=f"bench-skill-{index:05d}",
        version=1,
        title=f"Bench skill {index} for library scaling measurement",
        intent=f"Skill {index}, present only to grow the library while measuring startup.",
        task_class="repo-chore",
        steps=[Step(id="s0", intent="run a trivial command", tool="shell", inputs={"command": "true"})],
        certification_criteria=[
            SkillCertificationCriterion(
                id="done",
                kind="command",
                run="true",
                weight=1.0,
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="done",
                    negative_fixture="absent",
                    rejected=True,
                    checked_at=FIXED_TIME,
                ),
            )
        ],
        provenance=Provenance(
            distilled_from_run="bench",
            distilled_at=FIXED_TIME,
            curation="human_authored",
            derivation="hand_authored",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=FIXED_TIME),
    )


SECTIONS = {
    "retrieve-scaling": lambda root, rep, args: bench_retrieve_scaling(
        root, rep, iterations=args.iterations
    ),
    "walk-cost": lambda root, rep, args: bench_walk_cost(root, rep, hops=args.hops),
    "startup": lambda root, rep, args: bench_startup(root, rep, iterations=max(3, args.iterations // 4)),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=sorted(SECTIONS),
        action="append",
        help="Run only this section (repeatable). Default: all.",
    )
    parser.add_argument("--iterations", type=int, default=20, help="Timing iterations (min wins).")
    parser.add_argument("--hops", type=int, default=60, help="Walk length for walk-cost.")
    parser.add_argument("--json", action="store_true", help="Emit JSON rows instead of tables.")
    args = parser.parse_args(argv)

    reporter = Reporter(as_json=args.json)
    with tempfile.TemporaryDirectory(prefix="recertia-bench-") as tmp:
        root = Path(tmp)
        for name in args.only or sorted(SECTIONS):
            SECTIONS[name](root, reporter, args)
    reporter.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
