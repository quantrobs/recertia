"""The canonical ``bump-python-dep`` skill, as typed objects (ADR-0009; refactor-plan B5).

This is the fix for the specific B5 failure that motivated the ADR: the previous canonical
example in ``specifications.md`` §2 validated against the JSON Schema while missing several
prose-required fields. Building it here means ``tests/contracts/test_examples.py`` can assert
it passes the ``approved-skill`` semantic profile, not merely that it parses — and
``scripts/export_examples.py`` writes the exact same object to
``skills/bump-python-dep/v3/*.json`` for the documents to embed, so the two cannot drift.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.resources import ResourceClaim
from contracts.skill import (
    FailureMode,
    Hygiene,
    Parameter,
    Precondition,
    Provenance,
    SkillVersion,
    Step,
    StepLoop,
)
from contracts.stats import Contribution, SkillStats, Trust
from contracts.status import Certification, SkillStatus

_NOW = datetime(2026, 7, 30, 15, 22, 11, tzinfo=timezone.utc)


def bump_python_dep_version() -> SkillVersion:
    return SkillVersion(
        skill_id="bump-python-dep",
        version=3,
        supersedes=2,
        title="Bump a pinned Python dependency and repair fallout",
        intent=(
            "Raise a pinned dependency to a target version, then fix imports, type errors and "
            "test failures caused by the bump."
        ),
        task_class="repo-chore",
        tags=["python", "dependencies", "lockfile"],
        parameters=[
            Parameter(name="package", type="string", required=True),
            Parameter(
                name="target_version",
                type="string",
                required=False,
                description="Omit to take the latest compatible release.",
            ),
        ],
        preconditions=[
            Precondition(kind="file_exists", value="pyproject.toml"),
            Precondition(kind="command_succeeds", value="python -c 'import tomllib'"),
        ],
        steps=[
            Step(id="locate", tool="grep", intent="Find the current pin for {{package}}.", depends_on=[]),
            Step(
                id="changelog",
                tool="fetch",
                intent="Read the upstream changelog for breaking changes.",
                depends_on=[],
                resources=[ResourceClaim(kind="rate_limit", id="pypi", mode="write")],
            ),
            Step(
                id="edit",
                tool="edit_file",
                intent="Raise the pin to {{target_version}}.",
                depends_on=["locate"],
                resources=[ResourceClaim(kind="file", id="pyproject.toml", mode="write")],
            ),
            Step(id="sync", tool="shell", intent="Regenerate the lockfile.", depends_on=["edit"]),
            Step(
                id="repair",
                tool="agent_subtask",
                intent="Fix breakage surfaced by the type checker and tests.",
                depends_on=["sync", "changelog"],
                loop=StepLoop(until="criteria_pass", max_iterations=3),
            ),
        ],
        certification_criteria=[
            SkillCertificationCriterion(
                id="install",
                kind="command",
                run="uv sync --frozen",
                expect_exit=0,
                weight=1.0,
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="install",
                    negative_fixture="pre-bump workspace with a broken lockfile",
                    rejected=True,
                    checked_at=_NOW,
                    checked_against="sha256:env-fingerprint-v3",
                ),
            ),
            SkillCertificationCriterion(
                id="types",
                kind="command",
                run="mypy .",
                expect_exit=0,
                weight=1.0,
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="types",
                    negative_fixture="v2's stale-lockfile regression case",
                    rejected=True,
                    checked_at=_NOW,
                    checked_against="sha256:env-fingerprint-v3",
                ),
            ),
            SkillCertificationCriterion(
                id="tests",
                kind="command",
                run="pytest -q",
                expect_exit=0,
                weight=1.0,
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="tests",
                    negative_fixture="pre-bump workspace, unpatched",
                    rejected=True,
                    checked_at=_NOW,
                    checked_against="sha256:env-fingerprint-v3",
                ),
            ),
            SkillCertificationCriterion(
                id="scope",
                kind="judge",
                rubric="Only dependency-related files changed.",
                isolation="fresh_context",
                lens="scope",
                weight=0.3,
                preregistered=True,
            ),
        ],
        failure_modes=[
            FailureMode(
                symptom="Transitive pin conflict.",
                response="Relax the narrowest conflicting constraint, then re-run install.",
            )
        ],
        provenance=Provenance(
            distilled_from_run="01JD3K0000000000000000RUN3",
            distilled_at=_NOW,
            curation="human_authored",
            derivation="hand_authored",
            evolved_because="v2 left the lockfile stale when the bump was a no-op.",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=_NOW),
    )


def bump_python_dep_status() -> SkillStatus:
    return SkillStatus(
        skill_id="bump-python-dep",
        version=3,
        lifecycle="approved",
        active=True,
        certification=Certification(
            model_validated_on="claude-4.6-sonnet",
            tool_fingerprint={"uv": "0.5.10", "mypy": "1.13.0", "pytest": "8.3.4"},
            golden_set_ref="evals/golden/repo-chore/bump-python-dep.jsonl",
            last_recertified_at=_NOW,
            recert_status="fresh",
        ),
    )


def bump_python_dep_stats() -> SkillStats:
    return SkillStats(
        skill_id="bump-python-dep",
        version=3,
        trust=Trust(applications=14, successes=12, last_used_at=_NOW, lift_estimate=0.22, lift_samples=9),
        contribution=Contribution(
            applications=14,
            successes=12,
            baseline_success=0.55,
            interval_low=0.02,
            interval_high=0.38,
            last_evaluated_at=_NOW,
        ),
    )
