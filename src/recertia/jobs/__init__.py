"""M7 improvement-plane jobs: proposals only — never write approved directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from contracts.policy import JOB_PRIORITY_ORDER, JobPriority, JobQuota
from contracts.skill import SkillVersion
from recertia.memory.procedural.store import SkillStore
from recertia.review import ReviewService


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
    "compress",
    "fail_cluster",
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
    max_tokens: int = 0


@dataclass
class JobResult:
    job: str
    proposals: list[Proposal]
    spent_usd: float = 0.0
    skipped: str | None = None


class JobRunner:
    """Runs offline jobs under a budget; write path is proposals → review/golden only."""

    def __init__(
        self,
        store: SkillStore,
        *,
        reviewer: ReviewService | None = None,
        golden_root: Path | None = None,
        runs_root: Path | None = None,
        quota: JobQuota | None = None,
    ) -> None:
        self.store = store
        self.reviewer = reviewer
        self.golden_root = golden_root
        self.runs_root = runs_root or Path("/tmp/recertia-jobs")
        self.quota = quota or JobQuota()

    def admit(self, job: JobPriority, *, task_class: str | None = None, tokens: int = 0) -> bool:
        return self.quota.can_admit(job, task_class=task_class, tokens=tokens)

    def run(self, job_name: str, fn: Callable[[], list[Proposal]], *, budget: JobBudget) -> JobResult:
        priority: JobPriority | None = job_name if job_name in JOB_PRIORITY_ORDER else None
        tokens = budget.max_tokens
        if priority is not None and not self.admit(priority, tokens=tokens):
            return JobResult(job=job_name, proposals=[], skipped=f"quota refused {job_name}")
        proposals = fn()
        if len(proposals) > budget.max_proposals:
            raise JobError(f"job {job_name} exceeded max_proposals={budget.max_proposals}")
        if priority is not None and tokens:
            self.quota = self.quota.charge(priority, tokens)
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
