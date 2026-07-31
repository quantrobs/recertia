"""T0-T3 mutable-surface registry (ADR-0005).

Current layout covers the task plane (T0), skill/fact library surfaces (T1), distiller /
policy-shaped packages (T2), and never-autonomous measurement/containment surfaces (T3).
The rule that matters from day one: **nothing under ``fandea.nodes`` or ``fandea.jobs``
may import a T3 module.** ``tests/boundary/test_import_boundary.py`` asserts this statically,
by parsing the AST of every file rather than trusting that no one adds the import later.
"""

from __future__ import annotations

from typing import Literal

Tier = Literal["T0", "T1", "T2", "T3"]

TIER_BY_MODULE_PREFIX: dict[str, Tier] = {
    # T0 — task plane + derived / rebuildable state
    "fandea.nodes": "T0",
    "fandea.graph": "T0",
    "fandea.ledger": "T0",
    "fandea.workspace": "T0",
    "fandea.memory.affordance": "T0",
    "fandea.memory.episodic": "T0",
    "fandea.retrieval": "T0",
    "fandea.validation": "T0",
    "fandea.telemetry": "T0",
    "fandea.solver": "T0",
    "fandea.store": "T0",
    # T1 — policy-gated library surfaces (skills, facts, review, offline jobs)
    "fandea.memory.procedural": "T1",
    "fandea.memory.semantic": "T1",
    "fandea.memory.scope": "T1",
    "fandea.review": "T1",
    "fandea.jobs": "T1",
    # T2 — versioned guidance / criteria / thresholds (human + eval gate)
    "fandea.distill": "T2",
    # T3 — never autonomous (containment, measurement integrity, this boundary)
    "fandea.governance": "T3",
    "fandea.evals.ablation": "T3",
    "fandea.evals.fake_edges": "T3",
}

T3_FORBIDDEN_FOR_RUNS_AND_JOBS: tuple[str, ...] = (
    "fandea.governance",
    "fandea.evals.ablation",
)
"""Per ADR-0005: "the eval harness, ablation sampler, promotion thresholds, and sandbox policy
must be unreachable from any code path a run or job can invoke — enforced by module boundaries
and asserted in CI, not by convention." ``fandea.evals.fake_edges`` is T3-tiered for review
hygiene but may be read by offline jobs; only ``ablation`` and ``governance`` are import-forbidden
from ``fandea.nodes`` / ``fandea.jobs``.
"""


def tier_of(module_name: str) -> Tier | None:
    """Longest-prefix match against :data:`TIER_BY_MODULE_PREFIX`.

    Returns ``None`` for an untiered module — per ADR-0005, "an untiered mutable surface is a
    review blocker," so callers should treat ``None`` as a finding, not a default.
    """

    best: str | None = None
    for prefix in TIER_BY_MODULE_PREFIX:
        if module_name == prefix or module_name.startswith(prefix + "."):
            if best is None or len(prefix) > len(best):
                best = prefix
    return TIER_BY_MODULE_PREFIX[best] if best else None
