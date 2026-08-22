from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.criteria import SkillCertificationCriterion
from contracts.eval import BinomialSample
from contracts.skill import FailureMode, Hygiene, Provenance, SkillVersion, Step
from recertia.evals.faithfulness import (
    IntervenedSkillStore,
    bundle_hook_for,
    edit_distance,
    evaluate_faithfulness,
    event_kinds,
    jaccard,
    strategy_tag,
    trajectory_divergence,
)
from recertia.evals.interventions import apply_corrupt, apply_empty, apply_filler, apply_irrelevant
from recertia.ledger import HashChainLedger
from recertia.validation.sensitivity import author_sensitivity_proof, empty_negative_fixture


def _skill(skill_id: str = "used-skill", task_class: str = "repo-chore") -> SkillVersion:
    now = datetime.now(timezone.utc)
    cert = SkillCertificationCriterion(
        id="ok",
        kind="command",
        run="test -f pyproject.toml",
        preregistered=True,
        sensitivity_proof=author_sensitivity_proof(
            SkillCertificationCriterion(
                id="ok", kind="command", run="test -f pyproject.toml", preregistered=True
            ),
            negative_workdir=empty_negative_fixture(),
        ),
    )
    return SkillVersion(
        skill_id=skill_id,
        version=1,
        title=f"Title for {skill_id} skill body",
        intent=f"Apply {skill_id} when pyproject.toml exists and the bump is a patch release.",
        task_class=task_class,
        steps=[
            Step(
                id="step_1",
                tool="shell",
                intent="Bump the pinned dependency and refresh the lockfile",
                inputs={"command": "pip install -U package==1.2.3"},
            )
        ],
        certification_criteria=[cert],
        failure_modes=[
            FailureMode(
                symptom="Lockfile stays stale after a no-op bump",
                response="Force a lockfile rewrite and re-run the installer",
            )
        ],
        provenance=Provenance(distilled_from_run="r", distilled_at=now),
        hygiene=Hygiene(secret_scan="passed", scanned_at=now),
    )


def test_empty_drops_body_but_keeps_structure() -> None:
    original = _skill()
    emptied = apply_empty(original)
    assert emptied.skill_id == original.skill_id
    assert emptied.steps[0].id == original.steps[0].id
    assert emptied.steps[0].tool == "shell"
    assert emptied.steps[0].intent != original.steps[0].intent
    assert emptied.failure_modes == []


def test_corrupt_mutates_key_fields() -> None:
    original = _skill()
    corrupted = apply_corrupt(original)
    assert corrupted.steps[0].id == original.steps[0].id
    assert corrupted.steps[0].intent != original.steps[0].intent
    assert corrupted.failure_modes[0].symptom != original.failure_modes[0].symptom


def test_filler_is_non_semantic_same_length() -> None:
    original = _skill()
    filled = apply_filler(original)
    assert len(filled.steps[0].intent) == len(original.steps[0].intent)
    assert "Bump" not in filled.steps[0].intent


def test_irrelevant_swaps_distant_body() -> None:
    original = _skill()
    donor = _skill(skill_id="other-domain", task_class="research-synthesis")
    donor = donor.model_copy(
        update={
            "steps": [
                donor.steps[0].model_copy(
                    update={"intent": "Synthesize the brief from the notes corpus"}
                )
            ]
        }
    )
    swapped = apply_irrelevant(original, donor)
    assert swapped.skill_id == original.skill_id
    assert swapped.steps[0].intent == "Synthesize the brief from the notes corpus"


def test_used_skill_intervention_is_detectable() -> None:
    skill = _skill()
    report = evaluate_faithfulness(
        skill=skill,
        baseline=BinomialSample(successes=8, trials=10),
        baseline_events=["retrieval_result", "plan_choice", "step_started", "terminal"],
        outcomes={
            "empty": BinomialSample(successes=2, trials=10),
            "corrupt": BinomialSample(successes=3, trials=10),
            "filler": BinomialSample(successes=2, trials=10),
        },
        events={
            "empty": ["retrieval_result", "plan_choice", "terminal"],
            "corrupt": ["retrieval_result", "plan_choice", "step_started", "failure_classified", "terminal"],
            "filler": ["retrieval_result", "terminal"],
        },
        skill_used=True,
        min_independent_runs=5,
    )
    assert report.score > 0
    assert all(arm.detectable_change for arm in report.arms)
    assert all(arm.strategy.startswith("faithfulness:") for arm in report.arms)


def test_unused_skill_intervention_is_near_zero() -> None:
    skill = _skill("never-applied")
    events = ["retrieval_result", "plan_choice", "terminal"]
    report = evaluate_faithfulness(
        skill=skill,
        baseline=BinomialSample(successes=5, trials=10),
        baseline_events=events,
        outcomes={"empty": BinomialSample(successes=5, trials=10)},
        events={"empty": events},
        skill_used=False,
        min_independent_runs=5,
    )
    assert report.score == 0.0
    assert report.arms[0].divergence.jaccard == 1.0
    assert report.arms[0].divergence.edit_distance == 0
    assert report.arms[0].detectable_change is False


def test_jaccard_and_edit_distance() -> None:
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert edit_distance(["a", "b", "c"], ["a", "x", "c"]) == 1
    div = trajectory_divergence(["a", "b"], ["a"])
    assert div.jaccard < 1.0
    assert div.edit_distance == 1


def test_ledger_tag_cannot_be_mistaken_for_lift(tmp_path: Path) -> None:
    ledger = HashChainLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        actor="recertia-faithfulness",
        action="faithfulness_report",
        target="used-skill@v1",
        evidence={"score": 1.0, "tagged": True, "production_path": False},
        at=datetime.now(timezone.utc),
    )
    entry = ledger.entries()[0]
    assert entry.action == "faithfulness_report"
    assert entry.evidence["production_path"] is False
    assert strategy_tag("empty") == "faithfulness:empty"


def test_event_kinds_from_trajectory_objects() -> None:
    class _Ev:
        def __init__(self, kind: str) -> None:
            self.event_kind = kind

    assert event_kinds([_Ev("retrieval_result"), "plan_choice", _Ev("terminal")]) == [
        "retrieval_result",
        "plan_choice",
        "terminal",
    ]


def test_intervened_store_replaces_target_body_only() -> None:
    class _Inner:
        def __init__(self, skill: SkillVersion) -> None:
            self.skill = skill

        def get_version(self, skill_id: str, version: int) -> SkillVersion:
            return self.skill

    original = _skill()
    overlay = IntervenedSkillStore(
        _Inner(original),
        skill_id=original.skill_id,
        version=1,
        intervention="empty",
    )
    emptied = overlay.get_version(original.skill_id, 1)
    assert emptied.steps[0].intent != original.steps[0].intent
    assert emptied.failure_modes == []


def test_bundle_hook_for_irrelevant_swaps_identity() -> None:
    from contracts.run import MemoryBundle, SkillCandidateRef

    hook = bundle_hook_for(
        skill_id="used-skill",
        version=1,
        intervention="irrelevant",
        donor_id="other-domain",
        donor_version=2,
    )
    bundle = MemoryBundle(
        skills=[SkillCandidateRef(skill_id="used-skill", version=1, score=0.9)]
    )
    swapped = hook(bundle)
    assert swapped.skills[0].skill_id == "other-domain"
    assert swapped.skills[0].version == 2

