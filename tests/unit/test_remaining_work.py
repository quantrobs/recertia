"""Remaining-work CI gates RW-1…RW-8 (docs/specifications/remaining-work.md)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.eval import (
    BinomialSample,
    CausalLiftResult,
    ConfidenceInterval,
    MetricReport,
)
from contracts.policy import ImprovementFlags, Policy
from recertia.evals.metrics import build_metric_report
from recertia.evals.probes import run_probes
from recertia.evals.report import weekly_claim
from recertia.jobs import JobBudget, JobRunner
from recertia.jobs.workers import propose_hex_search
from recertia.memory.procedural.store import SkillStore

REPO = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_rw1_metric_report_schema_includes_yield_precision_decay() -> None:
    schema = MetricReport.model_json_schema()
    assert schema.get("additionalProperties") is False
    props = schema["properties"]
    for field in ("library_yield", "retrieval_precision_at_3", "retrieval_decay"):
        assert field in props
    with pytest.raises(Exception):
        MetricReport(snapshot_id="s", at=_NOW, unknown_field=1)  # type: ignore[call-arg]


def test_rw2_library_yield_unavailable_when_applications_not_recorded() -> None:
    report = build_metric_report(
        [
            {
                "is_eval_fixture": False,
                "arm": "treatment",
                "first_attempt_success": True,
            }
        ],
        snapshot_id="snap",
        approved_applied=None,
        approved_total=4,
    )
    assert report.library_yield is None
    assert "library_yield" in report.unavailable


def test_rw3_retrieval_decay_per_hundred_skills() -> None:
    report = build_metric_report(
        [],
        snapshot_id="snap",
        precision_at_3=0.7,
        prior_precision_at_3=1.0,
        skills_added=100,
    )
    assert report.retrieval_decay == pytest.approx(-0.3)
    assert report.retrieval_precision_at_3 == pytest.approx(0.7)


def test_rw4_probe_runner_meets_m1_floor(tmp_path: Path) -> None:
    result = run_probes(
        probes_path=REPO / "evals" / "probes" / "repo-chore.json",
        skills_root=REPO / "skills",
        index_path=tmp_path / "index.db",
        workdir_root=tmp_path / "work",
        env_fingerprint={"python": "3.12", "pytest": "8.3.4"},
        task_class="repo-chore",
    )
    assert result.probes
    assert result.precision_at_3 >= 0.7


def test_rw5_weekly_claim_never_labels_spanning_interval_as_improvement(
    tmp_path: Path,
) -> None:
    lying = build_metric_report([], snapshot_id="snap")
    lying = lying.model_copy(
        update={
            "causal_lift": CausalLiftResult(
                task_class="repo-chore",
                treatment=BinomialSample(successes=50, trials=100),
                control=BinomialSample(successes=50, trials=100),
                estimate=0.0,
                interval=ConfidenceInterval(low=-0.1, high=0.1, level=0.95),
                status="established_positive",
            )
        }
    )
    assert weekly_claim(lying) == "not established"

    eval_db = tmp_path / "evals.db"
    output = tmp_path / "weekly.json"
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "weekly_metrics_report.py"),
            "--eval-db",
            str(eval_db),
            "--skills-root",
            str(skills_root),
            "--output",
            str(output),
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    report = payload["report"]
    status = (report.get("causal_lift") or {}).get("status") or report.get(
        "unavailable", {}
    ).get("causal_lift")
    assert status
    interval = (report.get("causal_lift") or {}).get("interval")
    if interval is not None and interval["low"] <= 0 <= interval["high"]:
        assert payload["claim"] == "not established"
    assert payload["claim"] != "improvement"
    assert proc.returncode == 0


def test_rw6_hex_skips_without_practice_conversion(tmp_path: Path) -> None:
    policy = Policy(
        version="test",
        authoring_prior_version="ap-test",
        improvement=ImprovementFlags(practice_hex_search=True, curator_compress=True),
    )
    report = build_metric_report([], snapshot_id="snap")
    assert report.practice_conversion is None
    runner = JobRunner(SkillStore(tmp_path / "skills"), policy=policy)
    runner.enablement_report = report
    called = {"n": 0}

    def fn() -> list:
        called["n"] += 1
        return propose_hex_search()

    result = runner.run("practice_hex", fn, budget=JobBudget())
    assert result.skipped == "practice_conversion unavailable"
    assert result.proposals == []
    assert called["n"] == 0


def test_rw7_eval_runs_do_not_write_candidates(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from recertia.api import create_app

    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    app = create_app(root=tmp_path / "api-root", skills_root=skills_root)
    issued = app.state.api_keys.issue(
        tenant_id="t-eval", scopes={"metrics", "admin"}, actor="test"
    )
    client = TestClient(app)
    before = SkillStore(skills_root).list_versions()
    created = client.post(
        "/v1/evals/runs",
        json={
            "task_class": "repo-chore",
            "snapshot": "rw7",
            "golden_dir": "evals/golden/repo-chore/add-editorconfig",
        },
        headers={"X-API-Key": issued.secret},
    )
    assert created.status_code == 200, created.text
    after = SkillStore(skills_root).list_versions()
    assert after == before
    loaded = SkillStore(skills_root).iter_loaded()
    assert not any(status.lifecycle == "candidate" for _v, status, _s in loaded)


def test_rw8_budget_exhausted_uses_error_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from recertia.api import create_app

    monkeypatch.setenv("RECERTIA_TENANT_MAX_RUNS_PER_DAY", "0")
    app = create_app(root=tmp_path / "api-root", skills_root=tmp_path / "skills")
    issued = app.state.api_keys.issue(tenant_id="t-quota", scopes={"runs"}, actor="test")
    client = TestClient(app)
    created = client.post(
        "/v1/runs",
        json={"request": "hello", "task_class": "repo-chore", "run_id": "quota-1"},
        headers={"X-API-Key": issued.secret},
    )
    assert created.status_code == 429, created.text
    body = created.json()
    assert body["error"]["code"] == "budget_exhausted"
    assert body["error"]["retryable"] is False


def test_v1_http_exception_uses_envelope(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from recertia.api import create_app

    app = create_app(root=tmp_path / "api-root", skills_root=tmp_path / "skills")
    issued = app.state.api_keys.issue(tenant_id="t1", scopes={"runs"}, actor="test")
    client = TestClient(app)
    missing = client.get("/v1/runs/run-missing1", headers={"X-API-Key": issued.secret})
    assert missing.status_code == 404
    body = missing.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False
    assert "detail" not in body

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    invalid = client.post(
        "/v1/runs",
        json={},
        headers={"X-API-Key": issued.secret},
    )
    assert invalid.status_code == 422
    assert "detail" in invalid.json()
