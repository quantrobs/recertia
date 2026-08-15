#!/usr/bin/env python3
"""Weekly lift + canary + cost report (roadmap Phase 2 cadence).

Usage:
    python3 scripts/weekly_metrics_report.py --eval-db .recertia/evals.db --output report.json

Never claims lift when the Wilson interval includes zero (B7).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-db", type=Path, default=Path(".recertia/evals.db"))
    parser.add_argument("--task-class", default="repo-chore")
    parser.add_argument("--skills-root", type=Path, default=Path("skills"))
    parser.add_argument(
        "--canary-root", type=Path, default=Path("evals/canary/planted-failure")
    )
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    from recertia.evals.canary import run_judge_canary
    from recertia.evals.report import assemble_metric_report, weekly_claim
    from recertia.evals.store import EvalStore
    from recertia.memory.procedural.store import SkillStore

    store = EvalStore(args.eval_db)
    try:
        skill_store = SkillStore(args.skills_root)
        report = assemble_metric_report(
            store,
            skill_store=skill_store,
            task_class=args.task_class,
            snapshot_id=args.snapshot_id,
            model_version=args.model_version,
            canary_root=args.canary_root,
        )
    finally:
        store.close()

    canary = run_judge_canary(root=args.canary_root, model_version=args.model_version)
    claim = weekly_claim(report)
    payload = {
        "report": report.model_dump(mode="json"),
        "canary": {
            "trials": canary.trials,
            "false_passes": canary.false_passes,
            "false_pass_rate": canary.false_pass_rate,
            "model_version": canary.model_version,
        },
        "causal_lift_status": report.causal_lift.status if report.causal_lift else None,
        "claim": claim,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if claim == "not established":
        sys.stderr.write("claim=not established (interval includes zero)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
