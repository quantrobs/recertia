"""``SkillStats``: the derived, rebuildable half of ADR-0007's split (T0).

Never authored directly; always recomputed from the run store. Losing this record is a rebuild,
not a data-loss incident.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ApplyDiversity(BaseModel):
    """Distinct *application* sessions for the ``self_distilled`` evidence floor (ADR-0015).

    Authoring-time source sessions live on frozen ``Provenance``. This counter lives on
    ``SkillStats`` because it grows after the version is written (ADR-0007). The sample
    is dropped once ``distinct_apply_sessions >= floor`` so the row stays bounded.
    """

    model_config = ConfigDict(extra="forbid")

    distinct_apply_sessions: int = Field(default=0, ge=0)
    apply_session_sample: list[str] = Field(default_factory=list)
    floor: int = Field(default=30, ge=1)

    def note(self, session_id: str) -> "ApplyDiversity":
        if not session_id:
            return self
        if session_id in self.apply_session_sample:
            return self
        # Sample dropped once we hit the floor; counter is already sufficient for the gate.
        if not self.apply_session_sample and self.distinct_apply_sessions >= self.floor:
            return self
        count = self.distinct_apply_sessions + 1
        sample = list(self.apply_session_sample)
        sample.append(session_id)
        if count >= self.floor:
            sample = []
        return self.model_copy(
            update={"distinct_apply_sessions": count, "apply_session_sample": sample}
        )


class SkillStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: int
    predictive_trust: PredictiveTrust = PredictiveTrust()
    contribution: Contribution = Contribution()
    apply_diversity: ApplyDiversity = ApplyDiversity()

    @model_validator(mode="after")
    def _sample_bounded_by_floor(self) -> "SkillStats":
        sample = self.apply_diversity.apply_session_sample
        if len(sample) > self.apply_diversity.floor:
            raise ValueError("apply_session_sample longer than evidence floor")
        if self.apply_diversity.distinct_apply_sessions < len(sample):
            raise ValueError("distinct_apply_sessions smaller than the retained sample")
        return self
