"""Symbol → first-landing milestone map for R3 milestone-dependency CI."""

from __future__ import annotations

# Symbols that must not appear in an earlier milestone's done-when than their landing.
INTRODUCED_IN: dict[str, int] = {
    "causal_lift": 4,
    "ControlBaseline": 4,
    "ablation": 4,
    "PredictiveTrust": 4,
    "RetrievalAblationEffect": 4,
    "shadow_min_lift": 5,
    "active_cap_pressure": 5,
    "retirement_threshold": 5,
    "select_shadow_slots": 5,
    "merge_gap_rate": 4,
    "parallel_speedup": 4,
    "BudgetReservation": 6,
    "budget_excess": 6,
    "mean_composition_depth": 8,
    "JobRunner": 7,
    "SandboxPolicy": 9,
    "SandboxLimits": 9,
    "ApprovalGate": 9,
    "LocalExecutionCapability": 9,
    "ScopePromotion": 9,
    "pgvector": 9,
}
