"""T0–T3 self-modification boundary (ADR-0005), enforced by an import-boundary test.

Exports the tier registry used by CI. Sandbox types live in
:mod:`recertia.governance.sandbox` and are imported directly by operators — they are
intentionally not re-exported here so ``from recertia.governance import …`` stays a
narrow, reviewable surface.
"""

from recertia.governance.tiers import (
    T3_FORBIDDEN_FOR_RUNS_AND_JOBS,
    TIER_BY_MODULE_PREFIX,
    Tier,
    tier_of,
)

__all__ = [
    "T3_FORBIDDEN_FOR_RUNS_AND_JOBS",
    "TIER_BY_MODULE_PREFIX",
    "Tier",
    "tier_of",
]
