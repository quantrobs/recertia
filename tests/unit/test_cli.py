from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fandea.cli.main import app

runner = CliRunner()


def _spec(workdir: Path) -> dict:
    return {
        "task": {"request": "write output.txt"},
        "criteria": [
            {
                "id": "output-exists",
                "kind": "command",
                "run": "test -f output.txt",
                "source": "caller",
                "weight": 1.0,
                "sensitivity_proof": {
                    "criterion_id": "output-exists",
                    "negative_fixture": "empty workspace",
                    "rejected": True,
                    "checked_at": "2026-01-01T00:00:00Z",
                },
            }
        ],
        "script": ["python3 -c \"open('output.txt','w').write('done')\""],
        "workdir": str(workdir),
    }


def test_run_and_show_and_ledger_verify(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec(workdir)))
    runs_root = tmp_path / "runs"

    result = runner.invoke(
        app, ["run", "--spec", str(spec_path), "--runs-root", str(runs_root), "--run-id", "cli-run-1"]
    )
    assert result.exit_code == 0, result.output
    assert "terminal=solved" in result.output

    show_result = runner.invoke(
        app, ["runs", "show", "cli-run-1", "--runs-root", str(runs_root), "--route-log"]
    )
    assert show_result.exit_code == 0, show_result.output
    assert "terminal=solved" in show_result.output
    assert "distill" in show_result.output

    verify_result = runner.invoke(app, ["ledger", "verify", "--runs-root", str(runs_root)])
    assert verify_result.exit_code == 0, verify_result.output
    assert "ledger OK" in verify_result.output


def test_ledger_verify_on_empty_runs_root(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ledger", "verify", "--runs-root", str(tmp_path / "nothing-here")])
    assert result.exit_code == 0
    assert "0 entries" in result.output


def test_run_reports_unreservable_portfolio_budget_without_routing_error(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    spec = _spec(workdir)
    spec["task"]["request"] = "PORTFOLIO: write output.txt"
    spec["budget"] = {"max_attempts": 1}
    spec_path = tmp_path / "budget-spec.json"
    spec_path.write_text(json.dumps(spec))

    result = runner.invoke(
        app,
        [
            "run",
            "--spec",
            str(spec_path),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "cli-budget",
        ],
    )

    assert result.exit_code == 1
    assert "terminal=unsolved" in result.output
    assert "failure_class=budget" in result.output
    assert "RoutingError" not in result.output


def test_skills_promote_via_cli(tmp_path: Path) -> None:
    from fandea.memory.procedural.seeds import SEED_SKILLS, seed_stats, seed_status_draft
    from fandea.memory.procedural.store import SkillStore

    version = next(s for s in SEED_SKILLS if s.skill_id == "add-gitignore-entry")
    # Golden gate requires hashed rejecting sensitivity evidence on certification criteria.
    criteria = []
    for c in version.certification_criteria:
        proof = c.sensitivity_proof
        if proof is not None and proof.evidence_hash is None:
            proof = proof.model_copy(update={"evidence_hash": "sha256:test-promote-evidence"})
        criteria.append(c.model_copy(update={"sensitivity_proof": proof}))
    version = version.model_copy(update={"certification_criteria": criteria})

    store = SkillStore(tmp_path / "skills")
    store.write_version(version)
    store.write_status(seed_status_draft(version))
    store.write_stats(seed_stats(version))

    golden = tmp_path / "golden"
    (golden / "workspace").mkdir(parents=True)
    (golden / "workspace" / ".gitignore").write_text("*.egg-info/\n.venv/\n")
    (golden / "task.json").write_text(
        json.dumps(
            {
                "request": "Add *.pyc to the repository .gitignore",
                "task_class": "repo-chore",
                "expected_skill_id": "add-gitignore-entry",
            }
        )
        + "\n"
    )
    (golden / "expect.json").write_text(json.dumps({"terminal": "solved"}) + "\n")

    result = runner.invoke(
        app,
        [
            "skills",
            "promote",
            "add-gitignore-entry",
            "--version",
            "1",
            "--skills-root",
            str(tmp_path / "skills"),
            "--golden-dir",
            str(golden),
            "--runs-root",
            str(tmp_path / "runs"),
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "lifecycle=approved" in result.output
    assert store.get_status("add-gitignore-entry", 1).lifecycle == "approved"
