"""``SkillStats``: the derived, rebuildable half of ADR-0007's split (T0).

Never authored directly; always recomputed from the run store. Losing this record is a rebuild,
not a data-loss incident.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PredictiveTrust(BaseModel):
    """Observed success calibration for one skill, not a causal effect."""

    model_config = ConfigDict(extra="forbid")

    applications: int = Field(default=0, ge=0)
    successes: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    decayed_score: float | None = None

    @property
    def score(self) -> float:
        """Smoothed success ratio: ``(successes + 1) / (applications + 2)``."""

        return (self.successes + 1) / (self.applications + 2)


class RetrievalAblationEffect(BaseModel):
    """Class-level effect of making retrieval available versus suppressing it.

    This quantity is randomized at the retrieval boundary.  It deliberately has
    no skill identifier: it answers whether the library helps this task class,
    not whether one selected skill did.
    """

    model_config = ConfigDict(extra="forbid")

    task_class: str
    retrieval_enabled: int = Field(default=0, ge=0)
    retrieval_enabled_successes: int = Field(default=0, ge=0)
    retrieval_suppressed: int = Field(default=0, ge=0)
    retrieval_suppressed_successes: int = Field(default=0, ge=0)
    interval_low: float | None = None
    interval_high: float | None = None
    last_evaluated_at: datetime | None = None

    @property
    def estimate(self) -> float | None:
        if self.retrieval_enabled == 0 or self.retrieval_suppressed == 0:
            return None
        return (
            self.retrieval_enabled_successes / self.retrieval_enabled
            - self.retrieval_suppressed_successes / self.retrieval_suppressed
        )


class Contribution(BaseModel):
    """Per-skill shadow-versus-suppression effect; the retirement input.

    Scored from required non-``judge`` criteria only: a false-pass-biased model judge must not
    be able to disable contribution-based retirement (``references.md`` §1.8).
    """

    model_config = ConfigDict(extra="forbid")

    applications: int = Field(default=0, ge=0)
    successes: int = Field(default=0, ge=0)
    suppressed_applications: int = Field(default=0, ge=0)
    suppressed_successes: int = Field(default=0, ge=0)
    interval_low: float | None = None
    interval_high: float | None = None
    last_evaluated_at: datetime | None = None

    @property
    def estimate(self) -> float | None:
        """Shadow success rate minus this skill's suppressed success rate.

        ``None`` without both randomized shadow and suppression observations.  A
        task-class control is intentionally insufficient because selection into a
        particular skill is not random.
        """

        if self.applications == 0 or self.suppressed_applications == 0:
            return None
        return (
            (self.successes / self.applications)
            - (self.suppressed_successes / self.suppressed_applications)
        )


class SkillStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: int
    predictive_trust: PredictiveTrust = PredictiveTrust()
    contribution: Contribution = Contribution()
