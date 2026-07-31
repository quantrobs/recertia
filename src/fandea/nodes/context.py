"""What every node function receives besides the state (injected services for tests, too)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

from contracts.run import RunState
from fandea.ledger import HashChainLedger
from fandea.workspace import WorkspaceManager

if TYPE_CHECKING:
    from fandea.graph.ops import OperationLedger
    from fandea.memory.procedural.store import SkillStore
    from fandea.retrieval.pipeline import Retriever

T = TypeVar("T")


@dataclass
class NodeOutcome:
    """What a node function returns: the updated state, the chosen route, and why.

    ``route`` MUST name a ``predicate_name`` legal for this node's current state per
    ``contracts.graph.legal_routes`` — the orchestrator checks this before advancing, so a node
    cannot route somewhere the normative table forbids even though the node itself decides
    *which* legal route to take (e.g. ``review``'s approve/reject choice, which the route table
    intentionally leaves exogenous — specs §4.1).
    """

    state: RunState
    route: str | None
    note: str | None = None


@dataclass
class NodeContext:
    """Injected services. Node functions are otherwise pure functions of ``state``."""

    run_id: str
    attempt_no: int
    node: str
    workdir: Path
    workspaces: WorkspaceManager
    ledger: HashChainLedger
    ops: "OperationLedger"
    script: list[str] | None = None
    """Explicit scripted tool sequence. When None and strategy is ``apply``, ``solve`` derives
    a script from the chosen skill's shell steps (M1)."""

    retriever: "Retriever | None" = None
    store: "SkillStore | None" = None
    env_fingerprint: dict[str, str] = field(default_factory=dict)

    def op_once(self, op_seq: int, fn: Callable[[], T]) -> T:
        """At-least-once execution keyed by ``(run_id, attempt_no, node, op_seq)`` (ADR per B6)."""

        return self.ops.run_once(self.run_id, self.attempt_no, self.node, op_seq, fn)
