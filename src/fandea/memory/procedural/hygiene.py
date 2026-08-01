"""One-time secret/PII hygiene scan at store time (specs §2.4, §15.3).

Scans the skill's serialised content for high-signal secret and PII patterns (emails,
private keys, cloud/CI/API tokens). A failing scan refuses storage — the gate lives on
``SkillVersion.hygiene`` because it is evaluated once, before the document is ever written.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from contracts.skill import Hygiene, SkillVersion

# Emails, private keys, and common cloud/CI/API tokens. Patterns are intentionally
# high-signal; a match refuses storage rather than scrubbing silently (specs §15.3).
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret", re.compile(r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_oauth", re.compile(r"\bgho_[A-Za-z0-9]{36}\b")),
    ("github_fine_grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*\b")),
    ("api_key_assignment", re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"
    )),
    ("secret_assignment", re.compile(r"(?i)secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
)


def scan_findings(blob: str) -> list[str]:
    """Return human-readable labels for every matching secret/PII pattern."""

    return [label for label, pattern in _SECRET_PATTERNS if pattern.search(blob)]


def scan_skill(version: SkillVersion) -> Hygiene:
    blob = version.model_dump_json()
    if scan_findings(blob):
        return Hygiene(secret_scan="failed", scanned_at=datetime.now(timezone.utc))
    return Hygiene(secret_scan="passed", scanned_at=datetime.now(timezone.utc))


def require_clean(version: SkillVersion) -> SkillVersion:
    """Return ``version`` with a fresh passed hygiene stamp, or raise if secrets/PII are found.

    Hand-authored seed skills are expected to call this before ``SkillStore.write_version``.
    """

    blob = version.model_dump_json()
    findings = scan_findings(blob)
    if findings:
        raise ValueError(
            f"hygiene scan failed for {version.skill_id}@v{version.version}; "
            f"refusing to store ({', '.join(findings)}; specs §2.4)"
        )
    hygiene = Hygiene(secret_scan="passed", scanned_at=datetime.now(timezone.utc))
    return version.model_copy(update={"hygiene": hygiene})
