"""``SkillStats``: the derived, rebuildable half of ADR-0007's split (T0).

Never authored directly; always recomputed from the run store. Losing this record is a rebuild,
not a data-loss incident.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Trust(BaseModel):
    """Derived, never authored. A ratio is not causal evidence (specs §2.1, §7.1)."""

    model_config = ConfigDict(extra="forbid")

    applications: int = Field(default=0, ge=0)
    successes: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    lift_estimate: float | None = None
    lift_samples: int = Field(default=0, ge=0)
    decayed_score: float | None = None

    @property
    def score(self) -> float:
        """Smoothed success ratio: ``(successes + 1) / (applications + 2)``."""

        return (self.successes + 1) / (self.applications + 2)


class Contribution(BaseModel):
    """Per-skill lift over the control baseline; the retirement input (ADR-0006, specs §24.2).

    Scored from required non-``judge`` criteria only: a false-pass-biased model judge must not
    be able to disable contribution-based retirement (``references.md`` §1.8).
    """

    model_config = ConfigDict(extra="forbid")

    applications: int = Field(default=0, ge=0)
    successes: int = Field(default=0, ge=0)
    baseline_success: float | None = Field(default=None, ge=0, le=1)
    interval_low: float | None = None
    interval_high: float | None = None
    last_evaluated_at: datetime | None = None

    @property
    def estimate(self) -> float | None:
        """``ĉ(s) = successes/applications - baseline_success``, or ``None`` when inestimable.

        ``None`` when there are no control samples for the task class, or the skill has no
        required non-judge criterion — a skill in that state MUST NOT be retired (or protected
        from retirement) on contribution grounds (specs §24.2).
        """

        if self.applications == 0 or self.baseline_success is None:
            return None
        return (self.successes / self.applications) - self.baseline_success


class SkillStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: int
    trust: Trust = Trust()
    contribution: Contribution = Contribution()
