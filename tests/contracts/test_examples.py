"""The canonical example must pass its semantic profile, not merely parse (ADR-0009, B5)."""

from contracts.examples import (
    bump_python_dep_stats,
    bump_python_dep_status,
    bump_python_dep_version,
    repo_chore_retrieval_ablation,
)
from contracts.profiles import (
    validate_approved_skill,
    validate_candidate_skill,
    validate_retrieval_ablation,
    validate_skill_stats,
)


def test_canonical_example_is_internally_consistent():
    version = bump_python_dep_version()
    status = bump_python_dep_status()
    stats = bump_python_dep_stats()
    assert status.skill_id == version.skill_id == stats.skill_id
    assert status.version == version.version == stats.version


def test_canonical_example_passes_candidate_profile():
    version = bump_python_dep_version()
    status = bump_python_dep_status()
    assert validate_candidate_skill(version, status) == []


def test_canonical_example_passes_approved_profile():
    version = bump_python_dep_version()
    status = bump_python_dep_status()
    stats = bump_python_dep_stats()
    assert validate_approved_skill(version, status, stats) == []
    assert validate_skill_stats(stats) == []
    assert validate_retrieval_ablation(repo_chore_retrieval_ablation()) == []


def test_a_judge_only_skill_is_rejected_by_the_approved_profile():
    version = bump_python_dep_version()
    judge_only = version.model_copy(
        update={
            "certification_criteria": [
                c for c in version.certification_criteria if c.kind == "judge"
            ]
        }
    )
    status = bump_python_dep_status()
    stats = bump_python_dep_stats()
    violations = validate_approved_skill(judge_only, status, stats)
    assert any("judge-only" in v for v in violations)


def test_a_skill_missing_a_sensitivity_proof_fails_the_candidate_profile():
    version = bump_python_dep_version()
    unproven = version.model_copy(
        update={
            "certification_criteria": [
                c.model_copy(update={"sensitivity_proof": None})
                for c in version.certification_criteria
            ]
        }
    )
    status = bump_python_dep_status().model_copy(update={"lifecycle": "candidate", "active": False})
    violations = validate_candidate_skill(unproven, status)
    assert any("sensitivity proof" in v for v in violations)


def test_skill_stats_reject_incoherent_contribution_intervals():
    stats = bump_python_dep_stats().model_copy(
        update={
            "contribution": bump_python_dep_stats().contribution.model_copy(
                update={"suppressed_applications": 0, "interval_low": 0.1, "interval_high": 0.2}
            )
        }
    )
    violations = validate_skill_stats(stats)
    assert any("interval requires both" in v for v in violations)
