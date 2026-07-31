"""Shared helpers for hand-authored seed skill factories."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance

_NOW = datetime(2026, 7, 31, 0, 0, 0, tzinfo=timezone.utc)
_HYGIENE = Hygiene(secret_scan="passed", scanned_at=_NOW)
_AUTHOR = "seed-library"


def _proof(criterion_id: str, fixture: str) -> SensitivityProof:
    return SensitivityProof(
        criterion_id=criterion_id,
        negative_fixture=fixture,
        rejected=True,
        checked_at=_NOW,
        checked_against="sha256:m1-seed-env",
    )


def _cmd_criterion(cid: str, command: str, fixture: str) -> SkillCertificationCriterion:
    return SkillCertificationCriterion(
        id=cid,
        kind="command",
        run=command,
        expect_exit=0,
        weight=1.0,
        preregistered=True,
        authored_by="human",
        sensitivity_proof=_proof(cid, fixture),
    )


def _prov(skill_id: str) -> Provenance:
    return Provenance(
        distilled_from_run=f"seed:{skill_id}",
        distilled_at=_NOW,
        authored_by=_AUTHOR,
        curation="human_authored",
        derivation="hand_authored",
    )

