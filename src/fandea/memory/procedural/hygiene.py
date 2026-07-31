"""One-time secret/PII hygiene scan at store time (specs §2.4). M1 stub.

Scans the skill's serialised content for a small set of high-signal secret patterns. A
failing scan refuses storage — the gate lives on ``SkillVersion.hygiene`` because it is
evaluated once, before the document is ever written.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from contracts.skill import Hygiene, SkillVersion

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[a-z0-9_\-]{20,}"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"]?[a-z0-9_\-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
)


def scan_skill(version: SkillVersion) -> Hygiene:
    blob = version.model_dump_json()
    for pattern in _SECRET_PATTERNS:
        if pattern.search(blob):
            return Hygiene(secret_scan="failed", scanned_at=datetime.now(timezone.utc))
    return Hygiene(secret_scan="passed", scanned_at=datetime.now(timezone.utc))


def require_clean(version: SkillVersion) -> SkillVersion:
    """Return ``version`` with a fresh passed hygiene stamp, or raise if secrets are found.

    Hand-authored seed skills are expected to call this before ``SkillStore.write_version``.
    """

    hygiene = scan_skill(version)
    if hygiene.secret_scan != "passed":
        raise ValueError(
            f"hygiene scan failed for {version.skill_id}@v{version.version}; "
            "refusing to store (specs §2.4)"
        )
    return version.model_copy(update={"hygiene": hygiene})
