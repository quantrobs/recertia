#!/usr/bin/env python3
"""Export the canonical examples in contracts/examples.py to their canonical JSON paths.

Usage: python3 scripts/export_examples.py

Writes ``skills/bump-python-dep/v3/{version,status,stats}.json``. These are the objects
``docs/specifications.md`` §2 embeds and ``tests/contracts/test_examples.py`` checks — running
this script after changing ``contracts/examples.py`` keeps them from drifting apart.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contracts.examples import (  # noqa: E402
    bump_python_dep_stats,
    bump_python_dep_status,
    bump_python_dep_version,
)

FILES: dict[str, object] = {
    "version.json": bump_python_dep_version,
    "status.json": bump_python_dep_status,
    "stats.json": bump_python_dep_stats,
}


def render(filename: str) -> str:
    model = FILES[filename]()
    return json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=False) + "\n"


def write_all(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        (out_dir / filename).write_text(render(filename))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the export would change")
    args = parser.parse_args()

    out_dir = REPO_ROOT / "skills" / "bump-python-dep" / "v3"

    if not args.check:
        write_all(out_dir)
        print(f"Wrote {len(FILES)} file(s) to {out_dir}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        write_all(tmp_path)
        drift = []
        for filename in FILES:
            generated = (tmp_path / filename).read_text()
            existing = (out_dir / filename).read_text() if (out_dir / filename).exists() else None
            if generated != existing:
                drift.append(filename)
        if drift:
            print("Example drift detected in:", ", ".join(drift))
            print("Run `python3 scripts/export_examples.py` and commit the result.")
            return 1
        print("skills/bump-python-dep/v3/ matches contracts/examples.py — no drift.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
