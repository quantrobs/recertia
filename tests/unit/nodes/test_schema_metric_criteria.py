"""Tests for schema and metric CriterionKind runners plus sensitivity proofs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.criteria import SensitivityProof, SkillCertificationCriterion, TaskCriterion
from contracts.run import RunState
from recertia.nodes.context import NodeContext
from recertia.nodes.validate import PathEscapeError, _resolve_path, score_criteria, validate
from recertia.validation.sensitivity import author_sensitivity_proof, sensitivity_evidence_hash


def _proven(criterion: TaskCriterion) -> TaskCriterion:
    fingerprint = "empty"
    return criterion.model_copy(
        update={
            "sensitivity_proof": SensitivityProof(
                criterion_id=criterion.id,
                negative_fixture="empty",
                rejected=True,
                checked_at=datetime.now(timezone.utc),
                checked_against=f"sha256:{fingerprint}",
                evidence_hash=sensitivity_evidence_hash(criterion, fingerprint),
            )
        }
    )


def test_schema_criterion_passes_valid_artifact(base_state: RunState, ctx: NodeContext) -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    (ctx.workdir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (ctx.workdir / "artifact.json").write_text(json.dumps({"name": "ok"}), encoding="utf-8")
    criterion = _proven(
        TaskCriterion(
            id="shape",
            kind="schema",
            target="artifact.json",
            schema_ref="schema.json",
            source="caller",
        )
    )
    state = base_state.model_copy(update={"criteria": [criterion]})
    outcome = validate(state, ctx)
    assert outcome.route == "no_branches_and_passing"
    assert outcome.state.results[0].passed is True
    assert outcome.state.results[0].kind == "schema"


def test_schema_criterion_fails_invalid_artifact(base_state: RunState, ctx: NodeContext) -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    (ctx.workdir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (ctx.workdir / "artifact.json").write_text(json.dumps({"other": 1}), encoding="utf-8")
    criterion = _proven(
        TaskCriterion(
            id="shape",
            kind="schema",
            target="artifact.json",
            schema_ref="schema.json",
            source="caller",
        )
    )
    state = base_state.model_copy(update={"criteria": [criterion]})
    results, failure, _notes = score_criteria(state, ctx)
    assert results[0].passed is False
    assert failure is not None


def test_metric_criterion_compares_workdir_metrics(base_state: RunState, ctx: NodeContext) -> None:
    (ctx.workdir / "metrics.json").write_text(
        json.dumps({"latency_s": 0.4, "cost_usd": 1.2}), encoding="utf-8"
    )
    passing = _proven(
        TaskCriterion(
            id="latency",
            kind="metric",
            metric="latency_s",
            op="lt",
            threshold=1.0,
            source="caller",
        )
    )
    failing = _proven(
        TaskCriterion(
            id="cost",
            kind="metric",
            metric="cost_usd",
            op="lt",
            threshold=1.0,
            source="caller",
        )
    )
    state = base_state.model_copy(update={"criteria": [passing, failing]})
    outcome = validate(state, ctx)
    assert outcome.state.results[0].passed is True
    assert outcome.state.results[0].kind == "metric"
    assert outcome.state.results[1].passed is False
    assert outcome.route == "no_branches_and_failing"


def test_schema_sensitivity_proof_rejects_empty_fixture(tmp_path: Path) -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    negative = tmp_path / "neg"
    negative.mkdir()
    (negative / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (negative / "artifact.json").write_text(json.dumps({}), encoding="utf-8")
    criterion = SkillCertificationCriterion(
        id="shape",
        kind="schema",
        target="artifact.json",
        schema_ref="schema.json",
        preregistered=True,
    )
    proof = author_sensitivity_proof(criterion, negative_workdir=negative)
    assert proof.rejected is True
    assert proof.evidence_hash


def test_metric_sensitivity_proof_rejects_bad_metrics(tmp_path: Path) -> None:
    negative = tmp_path / "neg"
    negative.mkdir()
    (negative / "metrics.json").write_text(json.dumps({"latency_s": 9.0}), encoding="utf-8")
    criterion = SkillCertificationCriterion(
        id="latency",
        kind="metric",
        metric="latency_s",
        op="lt",
        threshold=1.0,
        preregistered=True,
    )
    proof = author_sensitivity_proof(criterion, negative_workdir=negative)
    assert proof.rejected is True


def test_schema_rejects_absolute_and_escaped_paths(base_state: RunState, ctx: NodeContext) -> None:
    outside = ctx.workdir.parent / "secret-schema.json"
    outside.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    (ctx.workdir / "artifact.json").write_text(json.dumps({"name": "ok"}), encoding="utf-8")

    with pytest.raises(PathEscapeError, match="absolute"):
        _resolve_path(ctx.workdir, str(outside))
    with pytest.raises(PathEscapeError, match="escape"):
        _resolve_path(ctx.workdir, "../secret-schema.json")

    absolute = _proven(
        TaskCriterion(
            id="abs",
            kind="schema",
            target="artifact.json",
            schema_ref=str(outside),
            source="caller",
        )
    )
    escaped = _proven(
        TaskCriterion(
            id="esc",
            kind="schema",
            target="../secret-schema.json",
            schema_ref="artifact.json",
            source="caller",
        )
    )
    state = base_state.model_copy(update={"criteria": [absolute, escaped]})
    results, _failure, _notes = score_criteria(state, ctx)
    assert results[0].passed is False
    assert results[0].errored is True
    assert "absolute" in results[0].output_excerpt
    assert results[1].passed is False
    assert results[1].errored is True
    assert "escape" in results[1].output_excerpt


def test_metric_path_stays_under_workdir(base_state: RunState, ctx: NodeContext, tmp_path: Path) -> None:
    # metrics.json is always resolved under workdir (never an outside sibling file).
    (tmp_path / "metrics.json").write_text(json.dumps({"latency_s": 0.1}), encoding="utf-8")
    resolved = _resolve_path(ctx.workdir, "metrics.json")
    assert resolved == (ctx.workdir / "metrics.json").resolve()
    assert not resolved.exists()

    criterion = _proven(
        TaskCriterion(
            id="latency",
            kind="metric",
            metric="latency_s",
            op="lt",
            threshold=1.0,
            source="caller",
        )
    )
    state = base_state.model_copy(update={"criteria": [criterion]})
    results, _failure, _notes = score_criteria(state, ctx)
    assert results[0].passed is False
    assert results[0].errored is True
    assert "metrics.json missing" in results[0].output_excerpt
