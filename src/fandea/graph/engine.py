"""The graph orchestrator: routing, checkpointing, and resume (specs §5.3, M0).

Owns state transitions and budget accounting; checkpoints after every node so a run is
resumable at node granularity (M0 done-when: "killing the process mid-run and resuming
completes it from the last checkpoint with no operation double-applied"). Routing itself is
never decided here — it is read from ``contracts.graph``, the normative route table — this
class only validates that a node's chosen route is legal and walks the resulting edge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from contracts.budget import Budget
from contracts.criteria import TaskCriterion
from contracts.graph import legal_routes
from contracts.run import RouteEntry, RunState, Task, WorkspaceSnapshot
from fandea.graph.ops import OperationLedger
from fandea.graph.store import CheckpointStore
from fandea.ledger import HashChainLedger
from fandea.nodes import NODE_FUNCS, NodeContext
from fandea.workspace import WorkspaceManager

MAX_GRAPH_STEPS = 500
"""A safety valve against a routing defect looping forever. Not a budget concept — a run that
legitimately needs this many node-hops has a routing bug, not a slow task."""


class RoutingError(RuntimeError):
    """A node chose an illegal route, or produced an ambiguous one it should have resolved."""


class GraphOrchestrator:
    def __init__(self, runs_root: Path | str) -> None:
        self.runs_root = Path(runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.checkpoints = CheckpointStore(self.runs_root / "checkpoints.db")
        self.ops = OperationLedger(self.runs_root / "operations.db")
        self.ledger = HashChainLedger(self.runs_root / "ledger.jsonl")
        self.workspaces = WorkspaceManager(self.runs_root / "snapshots")

    def close(self) -> None:
        self.checkpoints.close()
        self.ops.close()

    def start(
        self,
        run_id: str,
        task: Task,
        criteria: list[TaskCriterion],
        *,
        budget: Budget | None = None,
        workdir: Path | str,
        script: list[str] | None = None,
        max_steps: int | None = None,
    ) -> RunState:
        """Start a brand-new run at ``intake``.

        ``max_steps`` stops after that many node-hops, checkpointing normally, and returns the
        (not-yet-finalized) state — a genuine "process died here" simulation for resume tests,
        not just a mock.
        """

        state = RunState(run_id=run_id, task=task, criteria=criteria, budget=budget or Budget())
        return self._execute(state, "intake", workdir=Path(workdir), script=script, max_steps=max_steps)

    def resume(
        self,
        run_id: str,
        *,
        workdir: Path | str,
        script: list[str] | None = None,
        max_steps: int | None = None,
    ) -> RunState:
        """Resume from the last checkpoint. A no-op if the run already reached ``finalize``."""

        latest = self.checkpoints.latest(run_id)
        if latest is None:
            raise ValueError(f"no checkpoint found for run {run_id!r}")
        _, _, next_node, state = latest
        if next_node is None:
            return state
        return self._execute(state, next_node, workdir=Path(workdir), script=script, max_steps=max_steps)

    def _execute(
        self,
        state: RunState,
        node_name: str,
        *,
        workdir: Path,
        script: list[str] | None,
        max_steps: int | None = None,
    ) -> RunState:
        seq = self.checkpoints.latest(state.run_id)
        next_seq = (seq[0] + 1) if seq is not None else 0
        steps_taken = 0

        while True:
            steps_taken += 1
            if steps_taken > MAX_GRAPH_STEPS:
                raise RoutingError(
                    f"run {state.run_id!r} exceeded {MAX_GRAPH_STEPS} graph steps; likely a routing defect"
                )
            if max_steps is not None and steps_taken > max_steps:
                return state

            attempt_no_for_ctx = state.attempt_no + 1 if node_name == "solve" else state.attempt_no
            ctx = NodeContext(
                run_id=state.run_id,
                attempt_no=attempt_no_for_ctx,
                node=node_name,
                workdir=workdir,
                workspaces=self.workspaces,
                ledger=self.ledger,
                ops=self.ops,
                script=script,
            )
            outcome = NODE_FUNCS[node_name](state, ctx)
            new_state = outcome.state

            if node_name == "finalize":
                self.checkpoints.save(state.run_id, next_seq, node_name, None, new_state)
                return new_state

            legal = legal_routes(node_name, new_state)
            if outcome.route is not None:
                chosen = next((r for r in legal if r.predicate_name == outcome.route), None)
                if chosen is None:
                    raise RoutingError(
                        f"node {node_name!r} chose illegal route {outcome.route!r}; "
                        f"legal routes for this state: {[r.predicate_name for r in legal]}"
                    )
            else:
                if len(legal) != 1:
                    raise RoutingError(
                        f"node {node_name!r} produced an ambiguous state with no explicit route: "
                        f"{[r.predicate_name for r in legal]}; the node must choose"
                    )
                chosen = legal[0]

            if chosen.target == "solve" and not new_state.workspace_snapshots:
                ref = self.workspaces.snapshot(workdir, state.run_id, attempt_no=0)
                new_state = new_state.model_copy(
                    update={
                        "workspace_snapshots": [
                            WorkspaceSnapshot(attempt_no=0, snapshot_ref=ref, restored=False)
                        ]
                    }
                )

            route_entry = RouteEntry(
                node=node_name,
                route=chosen.predicate_name,
                reason=outcome.note or chosen.description,
                attempt_no=attempt_no_for_ctx,
                at=datetime.now(timezone.utc),
            )
            new_state = new_state.model_copy(update={"route_log": [*new_state.route_log, route_entry]})

            self.checkpoints.save(state.run_id, next_seq, node_name, chosen.target, new_state)
            next_seq += 1
            state = new_state
            node_name = chosen.target
