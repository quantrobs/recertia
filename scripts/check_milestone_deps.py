#!/usr/bin/env python3
"""R3: fail when a milestone done-when names a symbol introduced in a later milestone."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from contracts.introduced_in import INTRODUCED_IN  # noqa: E402

PLAN = REPO / "docs" / "archive" / "2026-Q3" / "implementation-plan.md"
MILESTONE_RE = re.compile(r"^## M(\d)\b", re.M)
DONE_WHEN_RE = re.compile(
    r"^\*\*Done when.*?\*\*\s*(.+?)(?=^\*\*Done when|\n## |\Z)",
    re.M | re.S,
)


def check(plan_path: Path = PLAN) -> list[str]:
    if not plan_path.is_file():
        return []
    text = plan_path.read_text(encoding="utf-8")
    milestones = [(m.start(), int(m.group(1))) for m in MILESTONE_RE.finditer(text)]
    errors: list[str] = []

    for match in DONE_WHEN_RE.finditer(text):
        body = match.group(1)
        # Milestone owning this done-when = last ## MN before the match.
        owners = [n for pos, n in milestones if pos < match.start()]
        if not owners:
            continue
        milestone = owners[-1]
        for symbol, introduced in INTRODUCED_IN.items():
            if symbol in body and introduced > milestone:
                errors.append(
                    f"M{milestone} done-when names {symbol!r} which is introduced_in=M{introduced}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", default=True)
    _ = parser.parse_args()
    errors = check()
    if errors:
        print("milestone-dependency check failed:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print("milestone-dependency check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
