"""Unit tests for fake-edge accounting from bindings + transcripts."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, InputBinding, Provenance, SkillVersion, Step, StepOutput
from fandea.evals.fake_edges import (
    fake_edge_checks,
    fake_edge_failure_count,
    iter_bound_outputs,
    unused_bound_outputs,
)
from fandea.evals.metrics import build_metric_report
from fandea.jobs.workers import propose_parallelise

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _skill_with_edge(*, bind: bool = True) -> SkillVersion:
    consume_bindings = (
        [InputBinding(input="value", source_step="produce", output="value")] if bind else []
    )
    return SkillVersion(
        skill_id="bound-demo",
        version=1,
        title="Bound demo skill title",
        intent="Intent long enough for a binding fake-edge unit test skill.",
        task_class="repo-chore",
        steps=[
            Step(
                id="produce",
                tool="shell",
                intent="Produce a typed stdout value for the consumer.",
                outputs=[StepOutput(name="value", type="string")],
            ),
            Step(
                id="consume",
                tool="shell",
                intent="Consume the producer output via an input binding.",
                input_bindings=consume_bindings,
            ),
        ],
        certification_criteria=[
            SkillCertificationCriterion(
                id="ok",
                kind="command",
                run="true",
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="ok",
                    negative_fixture="empty",
                    rejected=True,
                    checked_at=_NOW,
                ),
            )
        ],
        provenance=Provenance(
            distilled_from_run="unit",
            distilled_at=_NOW,
            curation="human_authored",
            derivation="hand_authored",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=_NOW),
    )


def _transcript(*, produced: bool, consumed: bool) -> dict:
    events: list[dict] = []
    if produced:
        events.append(
            {
                "kind": "step_output",
                "payload": {
                    "step_id": "produce",
                    "output": "value",
                    "type": "string",
                    "value": "payload",
                },
            }
        )
    events.append({"kind": "step_start", "payload": {"step_id": "produce", "input_bindings": []}})
    bindings = (
        [{"input": "value", "source_step": "produce", "output": "value"}] if consumed else []
    )
    events.append(
        {"kind": "step_start", "payload": {"step_id": "consume", "input_bindings": bindings}}
    )
    return {"run_id": "r1", "attempt_no": 1, "events": events}


def test_iter_bound_outputs_lists_declared_edges() -> None:
    skill = _skill_with_edge()
    edges = iter_bound_outputs(skill)
    assert len(edges) == 1
    assert edges[0].key == ("consume", "produce", "value")


def test_unused_bound_outputs_when_consumer_skips_binding() -> None:
    skill = _skill_with_edge()
    unused = unused_bound_outputs(skill, _transcript(produced=True, consumed=False))
    assert len(unused) == 1
    assert fake_edge_checks(skill, _transcript(produced=True, consumed=False)) == [False]


def test_partial_transcript_skips_unrun_bindings() -> None:
    skill = _skill_with_edge()
    partial = {
        "run_id": "r1",
        "attempt_no": 1,
        "events": [
            {"kind": "step_start", "payload": {"step_id": "produce", "input_bindings": []}},
        ],
    }
    assert unused_bound_outputs(skill, partial) == []
    assert fake_edge_checks(skill, partial) == []
    assert fake_edge_failure_count(skill, [partial] * 5) == 0
    assert not propose_parallelise(
        "bound-demo", 1, skill=skill, transcripts=[partial] * 5, threshold=5
    )


def test_real_edge_when_produced_and_consumed() -> None:
    skill = _skill_with_edge()
    assert unused_bound_outputs(skill, _transcript(produced=True, consumed=True)) == []
    assert fake_edge_checks(skill, _transcript(produced=True, consumed=True)) == [True]


def test_metric_report_wires_fake_edge_rate_from_checks() -> None:
    report = build_metric_report(
        [],
        snapshot_id="snap",
        fake_edge_checks=[True, False, False],
    )
    assert report.fake_edge_rate == 2 / 3
    assert "fake_edge_rate" not in report.unavailable
    assert "not yet available" not in report.unavailable.get("fake_edge_rate", "")


def test_metric_report_derives_from_skill_and_transcripts() -> None:
    skill = _skill_with_edge()
    report = build_metric_report(
        [],
        snapshot_id="snap",
        skill=skill,
        transcripts=[
            _transcript(produced=True, consumed=True),
            _transcript(produced=True, consumed=False),
        ],
    )
    assert report.fake_edge_rate == 0.5


def test_metric_report_unavailable_without_observations() -> None:
    report = build_metric_report([], snapshot_id="snap")
    assert report.fake_edge_rate is None
    assert report.unavailable["fake_edge_rate"] == "no fake edge observations supplied"
    assert "not yet available" not in report.unavailable["fake_edge_rate"]


def test_propose_parallelise_derives_from_history() -> None:
    skill = _skill_with_edge()
    history = [_transcript(produced=True, consumed=False) for _ in range(5)]
    proposals = propose_parallelise(
        "bound-demo", 1, skill=skill, transcripts=history, threshold=5
    )
    assert len(proposals) == 1
    assert proposals[0].payload["bindings"]
    assert proposals[0].payload["bindings"][0]["consumer_step"] == "consume"
    assert fake_edge_failure_count(skill, history) == 5
    assert not propose_parallelise(
        "bound-demo", 1, skill=skill, transcripts=history[:2], threshold=5
    )
