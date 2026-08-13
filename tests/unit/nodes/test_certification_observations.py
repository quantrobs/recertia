"""Certification observations are advisory and never gate the caller."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.criteria import SkillCertificationCriterion, TaskCriterion, mint_rejecting_proof
from contracts.run import RunState, SkillCandidateRef, Task
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from recertia.memory.procedural.capability import CandidateSkillStoreAdapter
from recertia.memory.procedural.store import SkillStore
from recertia.nodes.context import NodeContext
from recertia.nodes.validate import validate

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_certification_observations_do_not_change_route(
    base_state: RunState, ctx: NodeContext, tmp_path
) -> None:
    store = SkillStore(tmp_path / "skills")
    cert = SkillCertificationCriterion(
        id="must-exist",
        kind="command",
        run="test -f MISSING.txt",
        preregistered=True,
    )
    cert = cert.model_copy(
        update={"sensitivity_proof": mint_rejecting_proof(cert, fingerprint="obs")}
    )
    version = SkillVersion(
        skill_id="obs-skill",
        version=1,
        title="Observation fixture skill",
        intent="Used to prove certification observations are advisory only.",
        task_class="repo-chore",
        steps=[
            Step(
                id="noop",
                tool="shell",
                intent="No-op so the certification criterion can fail independently",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[cert],
        provenance=Provenance(
            distilled_from_run="obs",
            distilled_at=_NOW,
            curation="human_authored",
        ),
        hygiene=Hygiene(secret_scan="passed", scanned_at=_NOW),
    )
    store.write_candidate(version)
    task_crit = TaskCriterion(
        id="always",
        kind="command",
        run="true",
        source="caller",
        sensitivity_proof=mint_rejecting_proof(
            TaskCriterion(id="always", kind="command", run="true", source="caller"),
            fingerprint="always",
        ),
    )
    state = base_state.model_copy(
        update={
            "task": Task(
                task_id="t",
                request="do a thing",
                submitted_at=_NOW,
            ),
            "criteria": [task_crit],
            "chosen": SkillCandidateRef(skill_id="obs-skill", version=1, score=1.0),
        }
    )
    ctx.store = CandidateSkillStoreAdapter(store)
    ctx.node = "validate"
    outcome = validate(state, ctx)
    assert outcome.route == "no_branches_and_passing"
    assert outcome.state.failure_signal is None
    assert any(not o.passed for o in outcome.state.certification_observations)
    assert "advisory" in (outcome.note or "")
