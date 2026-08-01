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
    from recertia.evals.metrics import build_metric_report
    from recertia.evals.store import EvalStore
    from recertia.memory.procedural.active_set import recompute_active_set
    from recertia.memory.procedural.composition import mean_composition_depth
    from recertia.memory.procedural.store import SkillStore
    from recertia.review.autonomy_config import DEFAULT_AUTONOMY

    store = EvalStore(args.eval_db)
    try:
        rows = store.metric_rows(task_class=args.task_class, snapshot_id=args.snapshot_id)
        snap = args.snapshot_id or (rows[0]["snapshot_id"] if rows else "none")
        skill_store = SkillStore(args.skills_root)
        _u, pressure = recompute_active_set(skill_store, config=DEFAULT_AUTONOMY)
        mean_pressure = sum(pressure.values()) / len(pressure) if pressure else 0.0
        canary = run_judge_canary(root=args.canary_root, model_version=args.model_version)
        ever_benched = sum(
            1
            for _v, status, _s in skill_store.iter_loaded()
            if status.retirement.benched_at is not None or status.lifecycle == "benched"
        )
        restored = sum(
            1
            for _v, status, _s in skill_store.iter_loaded()
            if status.retirement.restored_at is not None
        )
        report = build_metric_report(
            rows,
            snapshot_id=snap,
            task_class=args.task_class,
            model_version=args.model_version,
            active_cap_pressure=mean_pressure,
            judge_false_pass_rate=canary.false_pass_rate,
            mean_composition_depth=mean_composition_depth(skill_store),
            retirement_benched=ever_benched or None,
            retirement_restored=restored if ever_benched else None,
        )
    finally:
        store.close()

    payload = {
        "report": report.model_dump(mode="json"),
        "canary": {
            "trials": canary.trials,
            "false_passes": canary.false_passes,
            "false_pass_rate": canary.false_pass_rate,
            "model_version": canary.model_version,
        },
        "claim": (
            "not established"
            if report.causal_lift is not None and report.causal_lift.status == "not_established"
            else (report.causal_lift.status if report.causal_lift else "insufficient_data")
        ),
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
