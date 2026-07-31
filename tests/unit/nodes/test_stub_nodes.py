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
from fandea.nodes.context import NodeContext
from fandea.nodes.fan_out import fan_out
from fandea.nodes.finalize import finalize
from fandea.nodes.join import join
from fandea.nodes.record_dead_end import record_dead_end
from fandea.nodes.reject_draft import reject_draft
from fandea.nodes.retrieve import retrieve
from fandea.nodes.review import review
from fandea.nodes.store import store


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


def test_review_auto_approves_in_m0(base_state: RunState, ctx: NodeContext) -> None:
    outcome = review(base_state, ctx)
    assert outcome.route == "approved"


def test_store_appends_a_ledger_entry(base_state: RunState, ctx: NodeContext) -> None:
    state = base_state.model_copy(update={"draft": {"skill_id": "demo-skill"}})
    outcome = store(state, ctx)
    assert outcome.route == "always"
    entries = ctx.ledger.entries()
    assert len(entries) == 1
    assert entries[0].target == "demo-skill"
    assert entries[0].action == "write"


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


def test_reject_draft_is_a_pure_identity_stub(base_state: RunState, ctx: NodeContext) -> None:
    outcome = reject_draft(base_state, ctx)
    assert outcome.state == base_state
    assert outcome.route == "always"


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
