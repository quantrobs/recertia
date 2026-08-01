"""Unit tests for store-time secret/PII hygiene."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.criteria import SensitivityProof, SkillCertificationCriterion
from contracts.skill import Hygiene, Provenance, SkillVersion, Step
from recertia.memory.procedural.hygiene import require_clean, scan_findings, scan_skill

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _version(*, intent_extra: str = "") -> SkillVersion:
    return SkillVersion(
        skill_id="hygiene-demo",
        version=1,
        title="Hygiene demo skill title",
        intent="A minimal skill used only to exercise store-time hygiene scanning." + intent_extra,
        task_class="repo-chore",
        steps=[
            Step(
                id="noop",
                tool="shell",
                intent="Do nothing useful in this hygiene fixture.",
                inputs={"command": "true"},
            )
        ],
        certification_criteria=[
            SkillCertificationCriterion(
                id="ok",
                kind="command",
                run="true",
                preregistered=True,
                sensitivity_proof=SensitivityProof(
                    criterion_id="ok",
                    negative_fixture="empty",
                    rejected=True,
                    checked_at=_NOW,
                ),
            )
        ],
        provenance=Provenance(
            distilled_from_run="unit",
            distilled_at=_NOW,
            curation="human_authored",
            derivation="hand_authored",
        ),
        hygiene=Hygiene(secret_scan="skipped"),
    )


def test_clean_skill_passes() -> None:
    version = _version()
    assert scan_skill(version).secret_scan == "passed"
    assert require_clean(version).hygiene.secret_scan == "passed"


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        (" contact me at alice@example.com please", "email"),
        (" -----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", "private_key"),
        (" key=AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        (" token=ghp_123456789012345678901234567890123456", "github_pat"),
        (" slack=xoxb-1234567890-abcdefghij", "slack_token"),
        (" openai=sk-abcdefghijklmnopqrstuvwxyz012345", "openai_key"),
        (" Authorization: Bearer ya29.a0AfH6SMB-exampletokenvalue", "bearer_token"),
        (
            " jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "jwt",
        ),
        (" api_key=supersecretvalue1234567890", "api_key_assignment"),
    ],
)
def test_hygiene_detects_pii_and_tokens(payload: str, label: str) -> None:
    dirty = _version(intent_extra=payload)
    findings = scan_findings(dirty.model_dump_json())
    assert label in findings
    assert scan_skill(dirty).secret_scan == "failed"
    with pytest.raises(ValueError, match="refusing to store"):
        require_clean(dirty)
