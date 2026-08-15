"""Retrieval defaults (T2 surfaces, specs §5 / §22). Hardcoded for M1; versioned policy later."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievalConfig:
    vector_top_k: int = 20
    lexical_top_k: int = 20
    rrf_k: int = 60
    rerank_top_n: int = 10
    min_score: float = 0.40
    max_candidates: int = 3
    probe_budget_units: int = 32
    """Maximum read-only probe cost spent filtering one retrieval candidate."""
    evidence_floor: int = 30
    low_evidence_factor: float = 0.85
    """Multiply score by this when applications < evidence_floor (demotion, never a hard drop)."""

    human_authored_prior: float = 1.0
    mined_prior: float = 0.95
    self_distilled_prior: float = 0.80
    """Curation prior favouring human_authored / mined over self_distilled (specs §5 §24)."""

    staleness_half_life_days: float = 90.0
    """Score halves every this many days since last successful application / certification."""

    # Environment fingerprint: tools whose versions must match when present on both sides.
    # A mismatch is a hard drop (precondition filter), not a demotion.
    env_fingerprint_tools: tuple[str, ...] = field(default_factory=lambda: ("python", "uv", "mypy", "pytest"))
