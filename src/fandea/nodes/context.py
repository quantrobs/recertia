"""What every node function receives besides the state (injected services)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol, TypeVar

from contracts.ledger import LedgerAction, LedgerEntry
from contracts.run import MemoryBundle, RunState
from contracts.skill import SkillVersion
from contracts.stats import SkillStats
from contracts.status import SkillStatus

if TYPE_CHECKING:
    from fandea.memory.affordance import AffordanceStore
    from fandea.memory.episodic import EpisodicStore
    from fandea.memory.semantic import FactStore
    from fandea.retrieval.pipeline import RetrievalExplanation
    from fandea.review import ReviewService
    from fandea.solver.apply import SkillApplicator
    from fandea.solver.model import ModelClient
    from fandea.solver.tools import ToolRuntime
    from fandea.solver.transcript import TranscriptStore

T = TypeVar("T")


class OperationRunner(Protocol):
    """The sole idempotency capability exposed to nodes."""

    def run_once(self, run_id: str, attempt_no: int, node: str, op_seq: int, fn: Callable[[], T]) -> T: ...


class WorkspaceCapability(Protocol):
    """Snapshot/restore capability; nodes never receive the backing snapshot store."""

    def snapshot(self, workdir: Path, run_id: str, *, attempt_no: int) -> str: ...

    def restore(self, workdir: Path, snapshot_ref: str) -> None: ...


class LedgerCapability(Protocol):
    """Append-only audit capability required by terminal nodes."""

    def append(
        self,
        *,
        actor: str,
        action: LedgerAction,
        target: str,
        evidence: dict[Any, Any] | None = None,
        at: datetime | None = None,
    ) -> LedgerEntry: ...


class RetrieverCapability(Protocol):
    """Search + index rebuild without exposing the backing ``SkillIndex``."""

    def search(
        self,
        query: str,
        *,
        workdir: Path,
        env_fingerprint: dict[str, str] | None = None,
        readable_scopes: set[str] | None = None,
        suppress: bool = False,
    ) -> tuple[MemoryBundle, RetrievalExplanation]: ...

    def rebuild(
        self,
        entries: list[tuple[SkillVersion, SkillStatus, SkillStats]],
    ) -> str: ...

    def snapshot_id(self) -> str: ...


class SkillStoreCapability(Protocol):
    """T0-facing skill library writes: candidates only (approved lifecycle is gated elsewhere)."""

    def write_candidate(self, version: SkillVersion) -> SkillVersion: ...

    def get_version(self, skill_id: str, version: int) -> SkillVersion: ...

    def get_status(self, skill_id: str, version: int) -> SkillStatus: ...

    def iter_loaded(self) -> list[tuple[SkillVersion, SkillStatus, SkillStats]]: ...


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
    workspaces: WorkspaceCapability
    ledger: LedgerCapability
    ops: OperationRunner
    script: list[str] | None = None
    retriever: RetrieverCapability | None = None
    store: SkillStoreCapability | None = None
    env_fingerprint: dict[str, str] = field(default_factory=dict)
    # Solver / memory services
    tools: "ToolRuntime | None" = None
    model: "ModelClient | None" = None
    # Independent verifier identity; a solver model must never judge its own artifact.
    verifier_model: "ModelClient | None" = None
    transcripts: "TranscriptStore | None" = None
    applicator: "SkillApplicator | None" = None
    episodic: "EpisodicStore | None" = None
    affordances: "AffordanceStore | None" = None
    # Distillation / review services
    facts: "FactStore | None" = None
    reviewer: "ReviewService | None" = None
    one_off_log: Path | None = None

    def op_once(self, op_seq: int, fn: Callable[[], T]) -> T:
        return self.ops.run_once(self.run_id, self.attempt_no, self.node, op_seq, fn)
