"""Unit tests for nodes that are unreachable on M0's default (scratch, no-fan-out) path.

Each is still a real function — exercised directly here with a fake ``NodeContext``, per the
test strategy in ``docs/implementation-plan.md`` ("nodes as pure (state) -> (delta, route)
functions with fake services").
"""

from __future__ import annotations

from contracts.branch import BranchState
from contracts.budget import Budget
from contracts.failure import FailureVerdict
from contracts.run import RunState
from recertia.nodes.context import NodeContext
from recertia.nodes.fan_out import fan_out
from recertia.nodes.finalize import finalize
from recertia.nodes.join import join
from recertia.nodes.record_dead_end import record_dead_end
from recertia.nodes.reject_draft import reject_draft
from recertia.nodes.retrieve import retrieve
from recertia.nodes.review import review
from recertia.nodes.store import store


def _branch(branch_id: str, status: str) -> BranchState:
    return BranchState(
        branch_id=branch_id,
        kind="portfolio",
        strategy="scratch",
        workspace_ref=f"ws-{branch_id}",
        status=status,
        budget=Budget(),
    )


def test_retrieve_returns_empty_unsuppressed_bundle(base_state: RunState, ctx: NodeContext) -> None:
    outcome = retrieve(base_state, ctx)
    assert outcome.route == "always"
    assert outcome.state.bundle.skills == []
    assert outcome.state.bundle.suppressed is False


def test_fan_out_is_a_pure_identity_stub(base_state: RunState, ctx: NodeContext) -> None:
    outcome = fan_out(base_state, ctx)
    assert outcome.state == base_state
    assert outcome.route == "always"


def test_join_flags_incomplete_merge(base_state: RunState, ctx: NodeContext) -> None:
    state = base_state.model_copy(
        update={"branches": [_branch("b1", "succeeded"), _branch("b2", "running")]}
    )
    outcome = join(state, ctx)
    assert outcome.route == "otherwise"
    assert outcome.state.merge_audits[-1].missing == ["b2"]


def test_join_passes_when_all_branches_settled_and_criteria_pass(
    base_state: RunState, ctx: NodeContext
) -> None:
    state = base_state.model_copy(update={"branches": [_branch("b1", "succeeded")]})
    outcome = join(state, ctx)
    assert outcome.route == "merge_complete_and_passing"


def test_review_rejects_missing_draft(base_state: RunState, ctx: NodeContext) -> None:
    outcome = review(base_state, ctx)
    assert outcome.route == "rejected"


def test_store_writes_skill_and_ledger(base_state: RunState, ctx: NodeContext, tmp_path) -> None:
    from datetime import datetime, timezone

    from contracts.criteria import SensitivityProof, SkillCertificationCriterion
    from contracts.skill import Hygiene, Provenance, SkillVersion, Step
    from recertia.memory.procedural.store import SkillStore

    proof = SensitivityProof(
        criterion_id="ok",
        negative_fixture="empty",
        rejected=True,
        checked_at=datetime.now(timezone.utc),
    )
    version = SkillVersion(
        skill_id="unit-demo-skill",
        version=1,
        title="Unit demo skill title",
        intent="Intent long enough for the skill version contract minimum.",
        task_class="repo-chore",
        steps=[
            Step(
                id="step_1",
                tool="shell",
                intent="Write a trivial marker file into the workspace",
                inputs={"command": "echo hi > output.txt"},
            )
        ],
        certification_criteria=[
            SkillCertificationCriterion(
                id="ok",
                kind="command",
                run="test -f output.txt",
                sensitivity_proof=proof,
                preregistered=True,
            )
        ],
        provenance=Provenance(
            distilled_from_run="unit-run",
            distilled_at=datetime.now(timezone.utc),
            curation="self_distilled",
            authoring_prior_version="ap-test",
        ),
        hygiene=Hygiene(secret_scan="skipped"),
    )
    ctx.store = SkillStore(tmp_path / "skills")
    state = base_state.model_copy(update={"draft": version.model_dump(mode="json")})
    outcome = store(state, ctx)
    assert outcome.route == "always"
    assert ctx.store.get_status("unit-demo-skill", 1).lifecycle == "candidate"
    entries = ctx.ledger.entries()
    assert entries[-1].action == "write"
    assert "unit-demo-skill" in entries[-1].target


def test_record_dead_end_surfaces_the_failure_class(base_state: RunState, ctx: NodeContext) -> None:
    state = base_state.model_copy(
        update={
            "failure": FailureVerdict(
                failure_class="execution", counts_against_trust=True, escalate_to_human=False
            )
        }
    )
    outcome = record_dead_end(state, ctx)
    assert outcome.route == "always"
    assert "execution" in outcome.note


def test_reject_draft_records_ledger(base_state: RunState, ctx: NodeContext) -> None:
    state = base_state.model_copy(update={"draft": {"skill_id": "demo-skill"}})
    outcome = reject_draft(state, ctx)
    assert outcome.state == state
    assert outcome.route == "always"
    assert ctx.ledger.entries()[-1].action == "policy_change"


def test_finalize_maps_predecessor_to_terminal(base_state: RunState, ctx: NodeContext) -> None:
    from datetime import datetime, timezone

    from contracts.run import RouteEntry

    for predecessor, expected in [
        ("plan", "abstained"),
        ("distill", "solved"),
        ("store", "solved"),
        ("record_dead_end", "unsolved"),
        ("reject_draft", "rejected"),
        ("something_unexpected", "error"),
    ]:
        state = base_state.model_copy(
            update={
                "route_log": [
                    RouteEntry(
                        node=predecessor, route="always", reason="x", at=datetime.now(timezone.utc)
                    )
                ]
            }
        )
        outcome = finalize(state, ctx)
        assert outcome.state.terminal == expected, predecessor
        assert outcome.route is None
