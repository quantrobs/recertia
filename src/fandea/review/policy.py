"""T2 policy proposals: require approver + eval comparison + ledger record (M9)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fandea.ledger import HashChainLedger


class PolicyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    document_path: str
    before_hash: str
    after_hash: str
    eval_comparison: str
    approver: str | None = None
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PolicyError(Exception):
    pass


def propose_policy_change(
    *,
    proposal_id: str,
    document_path: Path,
    before: str,
    after: str,
    eval_comparison: str,
) -> PolicyProposal:
    import hashlib

    return PolicyProposal(
        proposal_id=proposal_id,
        document_path=str(document_path),
        before_hash=hashlib.sha256(before.encode()).hexdigest(),
        after_hash=hashlib.sha256(after.encode()).hexdigest(),
        eval_comparison=eval_comparison,
    )


def approve_policy_change(
    proposal: PolicyProposal,
    *,
    approver: str,
    ledger: HashChainLedger,
    apply_to: Path | None = None,
    new_contents: str | None = None,
) -> PolicyProposal:
    if not approver.strip():
        raise PolicyError("T2 change requires a recorded approver")
    if not proposal.eval_comparison.strip():
        raise PolicyError("T2 change requires an eval comparison")
    approved = proposal.model_copy(
        update={"approver": approver, "status": "approved"}
    )
    ledger.append(
        actor=approver,
        action="policy_change",
        target=proposal.document_path,
        evidence={
            "proposal_id": proposal.proposal_id,
            "before_hash": proposal.before_hash,
            "after_hash": proposal.after_hash,
            "eval_comparison": proposal.eval_comparison,
        },
        at=datetime.now(timezone.utc),
    )
    if apply_to is not None and new_contents is not None:
        apply_to.write_text(new_contents, encoding="utf-8")
    return approved
