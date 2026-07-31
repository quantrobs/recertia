"""T0-T3 mutable-surface registry (ADR-0005).

M0 has no T1/T2 surfaces yet — no skill store (T1), no versioned policy documents (T2). What
exists is enforceable now: T0 (the task plane; runs and jobs write only derived/revertible
state) and T3 (this module itself, plus the eval harness and ablation sampler once M4 adds
them). The rule that matters from day one: **nothing under ``fandea.nodes`` or ``fandea.jobs``
may import a T3 module.** ``tests/boundary/test_import_boundary.py`` asserts this statically,
by parsing the AST of every file rather than trusting that no one adds the import later.
"""

from __future__ import annotations

from typing import Literal

Tier = Literal["T0", "T1", "T2", "T3"]

TIER_BY_MODULE_PREFIX: dict[str, Tier] = {
    "fandea.nodes": "T0",
    "fandea.graph": "T0",
    "fandea.ledger": "T0",
    "fandea.workspace": "T0",
    "fandea.governance": "T3",
}

T3_FORBIDDEN_FOR_RUNS_AND_JOBS: tuple[str, ...] = (
    "fandea.governance",
    "fandea.evals.ablation",
)
"""Per ADR-0005: "the eval harness, ablation sampler, promotion thresholds, and sandbox policy
must be unreachable from any code path a run or job can invoke — enforced by module boundaries
and asserted in CI, not by convention." ``fandea.evals.ablation`` does not exist until M4; the
boundary is declared here ahead of the code it will apply to, per refactor-plan B6.
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
