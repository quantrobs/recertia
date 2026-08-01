"""Default runtime wiring for CLI and API run startup.

Builds a ``GraphOrchestrator`` with the memory / retrieval / tool stack needed for
library apply paths — not a bare checkpoint engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fandea.governance.sandbox import ApprovalGate
from fandea.graph.engine import GraphOrchestrator
from fandea.memory.affordance import AffordanceStore
from fandea.memory.episodic import EpisodicStore
from fandea.memory.procedural.store import SkillStore
from fandea.memory.semantic import FactStore
from fandea.retrieval.index import SkillIndex
from fandea.retrieval.pipeline import Retriever
from fandea.solver.apply import SkillApplicator
from fandea.solver.tools import ClaimScheduler, ToolRuntime, default_registry
from fandea.solver.transcript import TranscriptStore
from fandea.workspace import WorkspaceManager


@dataclass
class OrchestratorBundle:
    """Orchestrator plus closable index handle."""

    orchestrator: GraphOrchestrator
    index: SkillIndex

    def close(self) -> None:
        self.orchestrator.close()
        self.index.close()


def build_default_orchestrator(
    runs_root: Path | str,
    *,
    skills_root: Path | str = Path("skills"),
    facts_root: Path | str = Path("facts"),
    index_path: Path | str | None = None,
    env_fingerprint: dict[str, str] | None = None,
    approve_default_tools: bool = True,
) -> OrchestratorBundle:
    """Wire SkillStore, Retriever, tools, applicator, episodic/facts/affordances."""

    runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    skills_root = Path(skills_root)
    facts_root = Path(facts_root)
    index_path = Path(index_path) if index_path is not None else runs_root / "skill_index.db"

    store = SkillStore(skills_root)
    index = SkillIndex(index_path)
    index.rebuild(store.iter_loaded())
    retriever = Retriever(index)

    registry = default_registry()
    gate = ApprovalGate()
    if approve_default_tools:
        for name in registry.names():
            gate.approve(name, actor="runtime-bootstrap", reason="default offline grant")
    tools = ToolRuntime(registry, ClaimScheduler(), approval_gate=gate)
    workspaces = WorkspaceManager(runs_root / "snapshots")
    transcripts = TranscriptStore(runs_root / "transcripts")
    applicator = SkillApplicator(tools, workspaces)

    orch = GraphOrchestrator(
        runs_root,
        store=store,
        retriever=retriever,
        tools=tools,
        transcripts=transcripts,
        applicator=applicator,
        episodic=EpisodicStore(runs_root / "episodic"),
        affordances=AffordanceStore(runs_root / "affordances.json"),
        facts=FactStore(facts_root),
        # Empty fingerprint: only mismatch when both sides declare a tool.
        env_fingerprint=env_fingerprint if env_fingerprint is not None else {},
    )
    # Share the same WorkspaceManager the applicator uses for attempt isolation.
    orch.workspaces = workspaces
    return OrchestratorBundle(orchestrator=orch, index=index)


def resolve_task_class(
    *,
    explicit: str | None,
    goal_task_class: str | None,
    default: str = "repo-chore",
) -> str:
    """Prefer caller override, then Goal.task_class, then the system default."""

    for candidate in (explicit, goal_task_class):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return default


def retrieval_query(*, request: str | None, goal_context: str | None, goal_terms: str = "") -> str:
    """Build a non-None retrieval query from request, goal context, or goal terms."""

    if request is not None and request.strip():
        return request.strip()
    if goal_context is not None and goal_context.strip():
        return goal_context.strip()
    if goal_terms.strip():
        return goal_terms.strip()
    return ""
