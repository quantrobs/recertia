#!/usr/bin/env python3
"""Nightly ``.recertia/`` backup helper (operator GA / RPO ≤ 24h).

    python3 scripts/backup_recertia.py --root .recertia --output backups/recertia.tar.gz

Cron example (nightly 02:00): ``0 2 * * * cd /path/to/recertia && python3 scripts/backup_recertia.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".recertia"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    from recertia.ops.backup import BackupError, backup_tree, default_archive_name

    archive = args.output if args.output is not None else Path("backups") / default_archive_name()
    try:
        dest = backup_tree(args.root, archive)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
