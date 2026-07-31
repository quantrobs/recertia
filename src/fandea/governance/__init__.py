"""The T0-T3 self-modification boundary (ADR-0005), enforced by an import-boundary test."""

from fandea.governance.tiers import T3_FORBIDDEN_FOR_RUNS_AND_JOBS, Tier, tier_of

__all__ = ["Tier", "tier_of", "T3_FORBIDDEN_FOR_RUNS_AND_JOBS"]
