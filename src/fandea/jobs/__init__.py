"""M7 improvement-plane jobs: proposals only — never write approved directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from contracts.skill import SkillVersion
from fandea.memory.procedural.store import SkillStore
from fandea.review import ReviewService


class JobError(Exception):
    """Job failed or attempted a forbidden write."""


ProposalKind = Literal[
    "mine",
    "curate",
    "practice",
    "recertify",
    "parallelise",
    "serialise",
    "correction",
]


@dataclass
class Proposal:
    kind: ProposalKind
    skill_id: str
    version: int
    rationale: str
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class JobBudget:
    max_proposals: int = 10
    max_cost_usd: float = 1.0


@dataclass
class JobResult:
    job: str
    proposals: list[Proposal]
    spent_usd: float = 0.0


class JobRunner:
    """Runs offline jobs under a budget; write path is proposals → review/golden only."""

    def __init__(
        self,
        store: SkillStore,
        *,
        reviewer: ReviewService | None = None,
        golden_root: Path | None = None,
        runs_root: Path | None = None,
    ) -> None:
        self.store = store
        self.reviewer = reviewer
        self.golden_root = golden_root
        self.runs_root = runs_root or Path("/tmp/fandea-jobs")

    def run(self, job_name: str, fn: Callable[[], list[Proposal]], *, budget: JobBudget) -> JobResult:
        proposals = fn()
        if len(proposals) > budget.max_proposals:
            raise JobError(f"job {job_name} exceeded max_proposals={budget.max_proposals}")
        return JobResult(job=job_name, proposals=proposals[: budget.max_proposals])

    def submit_proposal(self, proposal: Proposal, draft: SkillVersion) -> str:
        """Persist a candidate draft only — jobs never write ``approved`` (M7).

        Promotion remains an external golden-gate step outside the job plane.
        """

        self.store.write_candidate(draft)
        if self.reviewer is not None:
            decision = self.reviewer.decide(draft, run_id=f"job-{proposal.kind}")
            if decision.outcome != "approved":
                return f"rejected:{decision.note}"
            return f"candidate:{draft.skill_id}@v{draft.version}:review-ok"
        return f"candidate:{draft.skill_id}@v{draft.version}"
