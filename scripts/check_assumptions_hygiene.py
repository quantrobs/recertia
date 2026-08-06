#!/usr/bin/env python3
"""R3: fail when a milestone done-when treats an unverified assumption as a merge gate."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSUMPTIONS = REPO / "docs" / "assumptions.md"
PLAN = REPO / "docs" / "archive" / "2026-Q3" / "implementation-plan.md"

STATUS_RE = re.compile(
    r"^## (a\d+)\..+?\n(?:.*?\n)*?\- \*\*Status:\*\* `([^`]+)`",
    re.M,
)
DONE_WHEN_RE = re.compile(
    r"^\*\*Done when.*?\*\*\s*(.+?)(?=^\*\*Done when|\n## |\Z)",
    re.M | re.S,
)
ASSUMPTION_REF_RE = re.compile(r"assumptions\.md#(a\d+)|(?<![/\w])(a[123])(?![.\d\w])")


def parse_statuses(path: Path = ASSUMPTIONS) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in STATUS_RE.finditer(text)}


def check(plan_path: Path = PLAN, assumptions_path: Path = ASSUMPTIONS) -> list[str]:
    statuses = parse_statuses(assumptions_path)
    text = plan_path.read_text(encoding="utf-8")
    errors: list[str] = []
    for match in DONE_WHEN_RE.finditer(text):
        body = match.group(1)
        refs = set()
        for m in ASSUMPTION_REF_RE.finditer(body):
            refs.add(m.group(1) or m.group(2))
        for claim_id in sorted(refs):
            status = statuses.get(claim_id)
            if status is None:
                errors.append(f"done-when references unknown assumption {claim_id}")
                continue
            if status in ("supported", "refuted"):
                continue
            # Unverified claim may appear only when explicitly labelled research/not a merge gate.
            lowered = body.lower()
            ok_markers = (
                "research outcome",
                "not a merge gate",
                "not a condition of",
                "never a merge",
            )
            if not any(marker in lowered for marker in ok_markers):
                errors.append(
                    f"done-when cites {claim_id} (status={status}) without marking it "
                    f"as a research outcome / non-gate"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", default=True)
    _ = parser.parse_args()
    errors = check()
    if errors:
        print("assumptions-hygiene check failed:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print("assumptions-hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
