"""What every node function receives besides the state (injected services)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

from contracts.run import RunState
from fandea.ledger import HashChainLedger
from fandea.workspace import WorkspaceManager

if TYPE_CHECKING:
    from fandea.graph.ops import OperationLedger
    from fandea.memory.affordance import AffordanceStore
    from fandea.memory.episodic import EpisodicStore
    from fandea.memory.procedural.store import SkillStore
    from fandea.retrieval.pipeline import Retriever
    from fandea.solver.apply import SkillApplicator
    from fandea.solver.model import ModelClient
    from fandea.solver.tools import ToolRuntime
    from fandea.solver.transcript import TranscriptStore

T = TypeVar("T")


@dataclass
class NodeOutcome:
    """Updated state + chosen route predicate name (must be legal per contracts.graph)."""

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
    retriever: "Retriever | None" = None
    store: "SkillStore | None" = None
    env_fingerprint: dict[str, str] = field(default_factory=dict)
    # M2 services
    tools: "ToolRuntime | None" = None
    model: "ModelClient | None" = None
    transcripts: "TranscriptStore | None" = None
    applicator: "SkillApplicator | None" = None
    episodic: "EpisodicStore | None" = None
    affordances: "AffordanceStore | None" = None

    def op_once(self, op_seq: int, fn: Callable[[], T]) -> T:
        return self.ops.run_once(self.run_id, self.attempt_no, self.node, op_seq, fn)
