"""Critic pass: propose TaskCriteria when the caller supplies none (M3)."""

from __future__ import annotations

from pathlib import Path

from contracts.criteria import TaskCriterion
from fandea.validation.sensitivity import author_sensitivity_proof, empty_negative_fixture


def propose_criteria(request: str, *, workdir: Path | None = None) -> list[TaskCriterion]:
    """Author a minimal required command criterion from the request text.

    The proof is authored against an empty negative fixture so vacuous ``true`` criteria are
    detected (``rejected=False``) and remain advisory under validate's §15.2 rule.
    """

    check = _guess_check(request)
    criterion = TaskCriterion(
        id="critic-primary",
        kind="command",
        run=check,
        source="critic",
        weight=1.0,
    )
    neg = empty_negative_fixture(parent=workdir)
    proof = author_sensitivity_proof(criterion, negative_workdir=neg)
    return [criterion.model_copy(update={"sensitivity_proof": proof})]


def _guess_check(request: str) -> str:
    lower = request.lower()
    if "output.txt" in lower:
        return "test -f output.txt"
    if ".gitignore" in lower:
        return "test -f .gitignore"
    if "readme" in lower:
        return "test -f README.md"
    # Default: require *some* file exists — empty workspace fails this.
    return "test -n \"$(ls -A . 2>/dev/null)\""
