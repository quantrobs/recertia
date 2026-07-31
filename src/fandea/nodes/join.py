"""``join``: audit completeness and select/reduce fan-out branches (M6)."""

from __future__ import annotations

from contracts.branch import MergeAudit
from contracts.failure import FailureSignal, FailureVerdict
from contracts.run import RunState
from fandea.nodes._util import now
from fandea.nodes.context import NodeContext, NodeOutcome


def join(state: RunState, ctx: NodeContext) -> NodeOutcome:
    expected = len(state.branches)
    received = sum(1 for b in state.branches if b.status in ("succeeded", "failed"))
    missing = [b.branch_id for b in state.branches if b.status not in ("succeeded", "failed")]

    if missing:
        # One-shot re-dispatch of missing only (record audit, signal merge).
        audit = MergeAudit(
            merge_id=f"{ctx.run_id}-join-{len(state.merge_audits)}",
            expected=expected,
            received=received,
            missing=missing,
            action="flagged",
        )
        new_state = state.model_copy(
            update={
                "merge_audits": [*state.merge_audits, audit],
                "failure_signal": FailureSignal(
                    source="solver", detail=f"merge gap: missing={missing}", at=now()
                ),
                "failure": FailureVerdict(
                    failure_class="merge",
                    evidence=[f"missing branches: {missing}"],
                    counts_against_trust=False,
                    escalate_to_human=False,
                ),
            }
        )
        return NodeOutcome(
            state=new_state,
            route="otherwise",
            note=f"merge gap visible: missing={missing}",
        )

    audit = MergeAudit(
        merge_id=f"{ctx.run_id}-join-{len(state.merge_audits)}",
        expected=expected,
        received=received,
        missing=[],
        action="proceeded",
    )

    if state.strategy == "portfolio" or any(b.kind == "portfolio" for b in state.branches):
        winner = _select_portfolio_winner(state)
        branches = []
        for b in state.branches:
            branches.append(
                b.model_copy(update={"selected": b.branch_id == winner.branch_id})
                if winner
                else b
            )
        updates: dict = {
            "branches": branches,
            "merge_audits": [*state.merge_audits, audit],
        }
        # Keep validate's parent result vector; branch results are selection evidence only.
        new_state = state.model_copy(update=updates)
        note = f"portfolio winner={winner.branch_id if winner else None}"
    else:
        # Decomposition: all must succeed.
        if any(b.status != "succeeded" for b in state.branches):
            new_state = state.model_copy(
                update={
                    "merge_audits": [
                        *state.merge_audits,
                        audit.model_copy(update={"action": "failed"}),
                    ],
                    "failure_signal": FailureSignal(
                        source="solver", detail="decomposition branch failed", at=now()
                    ),
                }
            )
            return NodeOutcome(state=new_state, route="otherwise", note="decomposition incomplete")
        new_state = state.model_copy(update={"merge_audits": [*state.merge_audits, audit]})
        note = "decomposition merge complete"

    # Passing if no failure signal and required criteria on selected path ok.
    route = "merge_complete_and_passing"
    if new_state.failure_signal is not None:
        route = "otherwise"
    return NodeOutcome(state=new_state, route=route, note=note)


def _select_portfolio_winner(state: RunState):
    succeeded = [b for b in state.branches if b.status == "succeeded"]
    if not succeeded:
        return None

    def score(b) -> tuple[int, float, float]:
        # required-criteria pass count, then advisory score, then lower cost wins.
        req_pass = sum(1 for r in b.results if r.weight >= 1.0 and r.passed)
        advisory = sum(r.weight for r in b.results if r.passed and r.weight < 1.0)
        cost = -(b.cost_usd or b.spent.cost_usd or 0.0)
        return (req_pass, advisory, cost)

    return max(succeeded, key=score)
