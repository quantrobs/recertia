from __future__ import annotations

import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import CriterionResult, SkillCertificationCriterion, TaskCriterion
from contracts.run import RunManifest, RunState, SkillCandidateRef, Task
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from fandea.evals.metrics import build_metric_report
from fandea.evals.store import EvalStore, ObservationError
from fandea.memory.procedural.allocate import allocate_and_write
from fandea.memory.procedural.store import SkillStore


def _state(run_id: str, *, arm: str, chosen: bool = False) -> RunState:
    criterion = TaskCriterion(
        id="required-file",
        kind="command",
        run="test -f output.txt",
        source="caller",
    )
    return RunState(
        run_id=run_id,
        task=Task(
            task_id=run_id,
            request="create output.txt",
            task_class="repo-chore",
            submitted_at=datetime.now(timezone.utc),
        ),
        manifest=RunManifest(index_snapshot_id="snapshot-1", criteria_hash="locked"),
        arm=arm,  # type: ignore[arg-type]
        criteria=[criterion],
        criteria_locked_at=datetime.now(timezone.utc),
        chosen=(
            SkillCandidateRef(skill_id="evidence-skill", version=1, score=1.0) if chosen else None
        ),
        attempt_no=1,
        results=[CriterionResult(criterion_id="required-file", kind="command", passed=True)],
        terminal="solved",
    )


def _version() -> SkillVersion:
    now = datetime.now(timezone.utc)
    return SkillVersion(
        skill_id="process-safe",
        version=1,
        title="Process-safe allocation fixture",
        intent="A fixture used to verify durable allocation across worker processes.",
        task_class="repo-chore",
        steps=[Step(id="one", tool="shell", intent="No operation.", inputs={"command": "true"})],
        certification_criteria=[
            SkillCertificationCriterion(id="check", kind="command", run="true")
        ],
        provenance=Provenance(
            distilled_from_run="test",
            distilled_at=now,
            curation="human_authored",
            derivation="hand_authored",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=now),
    )


def _allocate_worker(root: str, queue: multiprocessing.Queue) -> None:
    version = allocate_and_write(SkillStore(root), _version())
    queue.put(version.version)


def test_run_derived_observations_are_append_only_and_feed_metrics(tmp_path: Path) -> None:
    store = EvalStore(tmp_path / "evals.sqlite")
    treatment = _state("treatment-1", arm="treatment", chosen=True)
    control = _state("control-1", arm="control")

    observation = store.append_run(treatment)
    store.append_run(control)
    assert observation.evidence_hash
    assert observation.valid_non_judge_evidence is True
    with pytest.raises(ObservationError, match="already has an immutable observation"):
        store.append_run(treatment)
    with pytest.raises(ObservationError, match="append_run-derived"):
        store.record_observation(observation)

    report = build_metric_report(
        store.metric_rows(task_class="repo-chore", snapshot_id="snapshot-1"),
        snapshot_id="snapshot-1",
        task_class="repo-chore",
    )
    assert report.first_attempt_success == 1.0
    assert report.causal_lift is not None
    treatment_sample, control_sample = store.contribution_samples(
        skill_id="evidence-skill", version=1, task_class="repo-chore"
    )
    assert (treatment_sample.successes, treatment_sample.trials) == (1, 1)
    assert (control_sample.successes, control_sample.trials) == (1, 1)
    store.close()


def test_version_allocation_is_safe_across_processes(tmp_path: Path) -> None:
    queue: multiprocessing.Queue = multiprocessing.Queue()
    workers = [
        multiprocessing.Process(target=_allocate_worker, args=(str(tmp_path / "skills"), queue))
        for _ in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    assert all(worker.exitcode == 0 for worker in workers)
    versions = sorted(queue.get(timeout=2) for _ in workers)
    assert versions == list(range(1, len(workers) + 1))
