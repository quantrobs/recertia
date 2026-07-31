"""``SkillVersion``: the immutable half of ADR-0007's three-way split.

Holds only what never changes after the version is written: identity, intent, steps,
certification criteria, provenance, and the one-time hygiene gate. Lifecycle, trust, and
contribution live in ``contracts/status.py`` and ``contracts/stats.py`` — importing this module
does not give you a mutable field to (mis)use.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.common import Curation, Derivation
from contracts.criteria import SkillCertificationCriterion
from contracts.resources import ResourceClaim

_SKILL_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_STEP_ID_PATTERN = r"^[a-z0-9]+(_[a-z0-9]+)*$"


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z_][a-z0-9_]*$")
    type: Literal["string", "number", "boolean", "path", "enum", "json"]
    required: bool = True
    default: object | None = None
    enum_values: list[str] | None = None
    description: str | None = None


class Precondition(BaseModel):
    """Evaluated by ``retrieve`` before a candidate is offered to ``plan`` (specs §2.1)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file_exists", "path_glob", "command_succeeds", "env_present", "tool_available"]
    value: str
    description: str | None = None


class StepLoop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: Literal["criteria_pass", "no_change", "predicate"]
    predicate: str | None = None
    max_iterations: int = Field(ge=1, le=10)


class Step(BaseModel):
    """One node in a skill's step DAG (specs §26.1).

    An edge is valid only if the step consumes the referenced step's output — the fake-edge
    test. This model cannot check that semantic property (it needs a run transcript); it only
    enforces the structural half: ids exist, are well-formed, and ``loop`` is bounded when
    present.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_STEP_ID_PATTERN)
    tool: str | None = None
    intent: str = Field(min_length=5)
    inputs: dict = Field(default_factory=dict)
    optional: bool = False
    depends_on: list[str] = Field(default_factory=list)
    resources: list[ResourceClaim] = Field(default_factory=list)
    loop: StepLoop | None = None


class FailureMode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symptom: str
    response: str


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distilled_from_run: str
    distilled_at: datetime
    authored_by: str | None = None
    curation: Curation = "self_distilled"
    derivation: Derivation | None = None
    failure_cluster_id: str | None = None
    authoring_prior_version: str | None = None
    evolved_because: str | None = None
    model: str | None = None


class Hygiene(BaseModel):
    """Store-time secret/PII scan. A one-time gate, so it stays on the immutable version."""

    model_config = ConfigDict(extra="forbid")

    secret_scan: Literal["passed", "failed", "skipped"]
    scanned_at: datetime | None = None


class SkillUse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(pattern=_SKILL_ID_PATTERN)
    version: int = Field(ge=1)


class SkillVersion(BaseModel):
    """Immutable once written (specs §1). Evolution produces version N+1 with ``supersedes``.

    Nothing on this model may be edited in place; there is no setter path, no mutable field, and
    the model is frozen at the Pydantic level so an attempted mutation raises rather than
    silently succeeding.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    skill_id: str = Field(pattern=_SKILL_ID_PATTERN)
    version: int = Field(ge=1)
    supersedes: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=8, max_length=120)
    intent: str = Field(min_length=20)
    task_class: str = Field(pattern=_SKILL_ID_PATTERN)
    tags: list[str] = Field(default_factory=list)
    scope: Literal["run", "project", "org", "global"] = "project"
    uses: list[SkillUse] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    preconditions: list[Precondition] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)
    certification_criteria: list[SkillCertificationCriterion] = Field(min_length=1)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    provenance: Provenance
    hygiene: Hygiene

    @model_validator(mode="after")
    def _steps_form_a_dag(self) -> "SkillVersion":
        ids = {step.id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("step ids must be unique")
        for step in self.steps:
            unknown = set(step.depends_on) - ids
            if unknown:
                raise ValueError(f"step {step.id!r} depends_on unknown step id(s): {unknown}")
        # Cycle detection (Kahn's algorithm).
        indegree = {step.id: 0 for step in self.steps}
        graph: dict[str, list[str]] = {step.id: [] for step in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                graph[dep].append(step.id)
                indegree[step.id] += 1
        queue = [sid for sid, deg in indegree.items() if deg == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for nxt in graph[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if visited != len(self.steps):
            raise ValueError("step depends_on graph contains a cycle")
        return self

    @model_validator(mode="after")
    def _at_least_one_non_judge_criterion(self) -> "SkillVersion":
        if all(c.kind == "judge" for c in self.certification_criteria):
            raise ValueError(
                "certification_criteria MUST contain at least one non-judge criterion "
                "(specs §2.1); a judge-only skill MUST NOT reach approved"
            )
        return self

    @model_validator(mode="after")
    def _parameters_cover_placeholders(self) -> "SkillVersion":
        declared = {p.name for p in self.parameters}
        used: set[str] = set()
        for step in self.steps:
            used |= _placeholders_in(step.intent)
            for v in step.inputs.values():
                if isinstance(v, str):
                    used |= _placeholders_in(v)
        for criterion in self.certification_criteria:
            for field in (criterion.run, criterion.rubric, criterion.expr):
                if field:
                    used |= _placeholders_in(field)
        unbound = used - declared
        if unbound:
            raise ValueError(f"unbound placeholder(s), not declared as parameters: {unbound}")
        return self

    @model_validator(mode="after")
    def _uses_within_depth(self) -> "SkillVersion":
        if len(self.uses) > 0 and len({(u.skill_id, u.version) for u in self.uses}) != len(
            self.uses
        ):
            raise ValueError("uses entries must be unique (skill_id, version) pairs")
        return self


def _placeholders_in(text: str) -> set[str]:
    import re

    return set(re.findall(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}", text))
