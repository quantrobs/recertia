# Fandea Specifications: 24. Library capacity and retirement

## 24. Library capacity and retirement

Contracts implementing [ADR-0006](../adr/0006-bounded-library-and-retirement.md).

### 24.1 Active set

| Rule | Detail |
| --- | --- |
| Retrievability | Only skills in the active set are retrievable for application |
| Cap | `active_cap` per task class, default 50; MUST be finite |
| Selection | Rank `approved` versions by `contribution.estimate`, then `predictive_trust`, then recency; the top `active_cap` are `active` |
| Overflow | Versions outside the cap become `benched`, not deleted |
| Re-evaluation | The Curator recomputes the active set on schedule and after any promotion |
| Newly approved skills | Enter active with a protected grace period of `evidence_floor` applications, so a new skill is not benched before it can be measured |
| Shadow / exploration slots | Up to `shadow_slots_per_task_class` (default 3) offline slots per class for `benched` and inactive `approved` versions; these MUST NOT expand the caller-visible active set or affect the caller's result |

The grace period matters: without it, a cap plus a contribution ranking would permanently favour
incumbents, and no new skill could ever accumulate the evidence needed to displace one. Shadow
slots are how a benched version gathers restoration evidence without becoming retrievable for
application.

### 24.2 Three separated quantities

Per [ADR-0007](../adr/0007-skill-identity-status-and-stats-split.md) and the S4 split, three
quantities answer three different questions. Mixing them was the bug: subtracting a task-class
control baseline from a non-randomly selected skill attributes library-level lift to one skill.

| Quantity | Lives on | Answers | Randomized at |
| --- | --- | --- | --- |
| `PredictiveTrust` | `SkillStats.predictive_trust` | Calibration: how often did this skill succeed when applied? | — (observational) |
| `RetrievalAblationEffect` | Eval store, keyed by `task_class` | Does making retrieval available help this class? | Retrieval boundary (treatment vs control) |
| `Contribution` | `SkillStats.contribution` | Does *this* skill help vs suppressing it? | Per-skill shadow vs suppression |

`estimate` on both effect models is a computed property, never a stored field.

```python
class PredictiveTrust(BaseModel):
    applications: int = 0
    successes: int = 0
    last_used_at: datetime | None = None
    decayed_score: float | None = None

    @property
    def score(self) -> float:
        return (self.successes + 1) / (self.applications + 2)

class RetrievalAblationEffect(BaseModel):
    task_class: str
    retrieval_enabled: int = 0
    retrieval_enabled_successes: int = 0
    retrieval_suppressed: int = 0
    retrieval_suppressed_successes: int = 0
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
    applications: int = 0                 # shadow trials
    successes: int = 0
    suppressed_applications: int = 0
    suppressed_successes: int = 0
    interval_low: float | None = None     # Wilson/Newcombe interval on the difference
    interval_high: float | None = None
    last_evaluated_at: datetime | None = None

    @property
    def estimate(self) -> float | None:
        # ĉ(s) = shadow success rate − this skill's suppressed success rate.
        if self.applications == 0 or self.suppressed_applications == 0:
            return None
        return (
            (self.successes / self.applications)
            - (self.suppressed_successes / self.suppressed_applications)
        )
```

Rules: success on both arms is scored from **required non-`judge` criteria only**, because a
false-pass-biased model judge silently disables contribution-based retirement
(`references.md` §1.8); `environment`, `tool`, `budget`, and `merge` failure classes are
excluded from denominators (§16); when either shadow or suppression arm lacks observations, or a
skill has no required non-`judge` criterion, contribution is `null` and the skill MUST NOT be
retired (or protected from retirement) on contribution grounds. Class-level
`RetrievalAblationEffect` MUST NOT be used as a per-skill `baseline_success` substitute.

### 24.3 Retirement

```text
bench(s)  : applications >= evidence_floor          (default 30)
            AND estimate <= -retirement_threshold   (default 0.10)
restore(s): estimate > -retirement_threshold on later evidence,
            OR Curator revision produces a new version that validates
never     : applications < evidence_floor           → demote score only
```

Additional rules: retirement is per version, not per skill; a benched version's parents (§14) are
marked `needs_recert`, since composition pins may now reference a non-active child; benching MUST
be recorded in the ledger (§21) with the contribution evidence that justified it.

Defaults are deliberately loose. A harsh configuration (evidence floor 20, threshold 0) measured
*below* the no-library baseline (`references.md` §1.2), so `evidence_floor` and
`retirement_threshold` MUST be changed together and validated jointly against the golden sets.

### 24.4 Floor property

With finite `active_cap` and `retirement_threshold`, expected performance is bounded below the
no-memory baseline by a margin depending only on the threshold, the estimator tolerance, and the
cap. The finiteness of both is a T3 invariant (§22) and MUST be asserted in CI: an unbounded cap
or a zero threshold removes the floor entirely rather than merely loosening it.

## 25. Authoring prior and failure-cluster distillation

### 25.1 Authoring prior

A versioned document (T2) constraining how the distiller writes skills: granularity, naming,
parameter conventions, step phrasing, and how `failure_modes` should be expressed. Every skill
version records `provenance.authoring_prior_version`.

Rules: the prior MUST be applied on both distillation paths; changing it requires an eval
comparison (§22); and since a consistent prior largely subsumes explicit deduplication
(`references.md` §1.3), Curator deduplication MUST NOT be treated as a prerequisite for shipping
distillation.

### 25.2 Failure-cluster path

| Stage | Rule |
| --- | --- |
| Cluster | Group episodic `dead_end` records by task class and normalised failure signature |
| Threshold | A cluster with ≥3 distinct runs is eligible for authoring |
| Output | A pitfall-oriented skill whose substance is `preconditions` and `failure_modes`, plus a minimal corrective step sequence |
| Criteria | MUST include a criterion that fails on the recorded failure signature — the sensitivity proof is the cluster itself (§15.2) |
| Provenance | `self_distilled`, with `distilled_from_run` set to the cluster's representative run and the cluster id recorded |

Failure-derived skills are validated identically to success-derived ones. Their advantage is that
a known-bad artifact for the sensitivity proof already exists, which makes them the cheapest
skills in the system to certify honestly.

## 26. Concurrency, isolation, and merges

Contracts for the graph-execution rules in `architecture/task-plane.md` §5.6 and §5.10 and
`architecture/skill-composition.md` §6.1. Sourced from the practitioner account in
[`references.md`](../references.md) §1.7.

### 26.1 Step dependency graphs

| Rule | Detail |
| --- | --- |
| Declaration | Dependencies are derived exclusively from `input_bindings`; there is no free-floating `depends_on` authoring field |
| Validity | Each binding MUST name a predecessor step id and an output that predecessor declares. Ordering-only edges cannot be authored |
| Structure | The derived step graph MUST be acyclic; unknown source steps or undeclared outputs fail at store time |
| Execution | Steps whose derived dependencies are satisfied run concurrently, subject to §26.2 |
| Authoring | The authoring prior (§25.1) instructs the distiller to emit bindings only when a later step consumes a named earlier output |
| Curation | The Curator MAY propose removing a binding; such a proposal MUST show that the dependent step's outcome is unchanged when the binding is dropped |

Concurrency is bounded by `max_parallel_steps` (default 8) so a wide skill cannot exhaust
tool-runtime capacity.

Execution proceeds in **waves**: the scheduler takes all steps whose derived dependencies are
satisfied and whose claims do not conflict with a running step, dispatches up to
`max_parallel_steps` of them, and waits for the wave before computing the next. Waves are
recorded in `state.step_waves` in order, which keeps a parallel attempt as replayable as a
serial one — the transcript alone cannot tell you what ran together. A wave is the unit of
rollback: `evolve` restores the snapshot taken before the wave started, never a partial wave.

### 26.2 Resource claims

```python
class ResourceClaim(BaseModel):
    kind: Literal["file", "path", "service", "rate_limit", "lock", "external_system"]
    id: str
    mode: Literal["read", "write", "exclusive"]

class ResourceConflict(BaseModel):
    claim: ResourceClaim
    waiting: str               # step or branch id
    holder: str                # step or branch id holding the claim
    waited_ms: int
    resolution: Literal["acquired", "timed_out", "deadlock_serialised"]
```

| Rule | Detail |
| --- | --- |
| Conflict | Two units conflict when they claim the same `id` and at least one mode is `write` or `exclusive` |
| Effect | Conflicting units MUST NOT run concurrently, even with no `input_bindings`-derived edge between them and even in separate workspaces |
| Scope | Applies to steps within a skill, to branches under fan-out, and to concurrent runs sharing an external system |
| Undeclared claims | A tool that touches a shared resource without declaring it is a defect; the tool registry (T3) is where claims are declared |
| Rate limits | Modelled as a `rate_limit` resource with `write` mode, so contention serialises rather than failing under load |
| Acquisition order | Claims are acquired in a fixed global order (`kind`, then `id`), which makes hold-and-wait cycles impossible between units that declare honestly |
| Undeclared deadlock | A wait exceeding `claim_timeout_s` (default 60) is a `merge` failure (§16); the repair re-runs the wave serially and records a `serialise` signal for the Curator |
| Observation | Every wait is recorded as a `ResourceConflict` and aggregated into the affordance plane (§13.4), so contention becomes a scheduling input rather than folklore |

Workspace isolation is necessary but not sufficient: the collisions that matter most —
rate-limited APIs, external systems, shared locks — live outside the workspace entirely.

### 26.3 Verifier isolation and triangulation

| Rule | Detail |
| --- | --- |
| Fresh context | A `judge` criterion MUST be evaluated with only the artifact under test and the rubric in context. Solver transcripts, plans, and prior justifications MUST be excluded |
| No self-grading | The model instance that produced an artifact MUST NOT score it |
| Distinct lenses | When a skill has multiple `judge` criteria, they MUST use distinct `lens` values; duplicate lenses collapse to one for scoring |
| Recording | The isolation mode and lens are recorded with each result, so an inherited-context evaluation is auditable after the fact |
| Standing limit | Judges remain advisory: promotion still requires a non-`judge` certification criterion (§2.4) |

The reason for the fresh-context rule is that a judge sharing the worker's context measures
agreement with the reasoning that produced the artifact, which is the self-grading failure the
whole verification design exists to avoid — reintroduced under a second name.

### 26.4 Merge completeness and layered fan-in

```python
class MergeAudit(BaseModel):
    merge_id: str
    expected: int
    received: int
    missing: list[str] = []
    action: Literal["proceeded", "flagged", "failed"]
    layered: bool = False

    @property
    def is_complete(self) -> bool:
        # The real predicate §4.1's routing table needs. There is no stored `.complete` field.
        return self.received >= self.expected and not self.missing
```

| Rule | Detail |
| --- | --- |
| Count | Every fan-in MUST record expected against received inputs |
| Gap handling | `decomposition` joins MUST NOT synthesise across a gap: the audit routes to `classify_failure`, which files a `merge` verdict and re-dispatches only the missing branches once (§16). `portfolio` joins MAY proceed on a gap, because a race with a surviving winner is still a valid result, but MUST flag it |
| No silent partials | A merge MUST NOT emit a result that is indistinguishable from a complete one when inputs are missing |
| Layering | Merges above `layer_threshold` inputs (default 8) MUST batch, summarise per batch, then combine summaries, rather than concatenating raw outputs |
| Deterministic reduction | Where combination is mechanical, reduction MUST use code rather than a model |

The silent-partial rule addresses the failure mode specific to graphs: in a chain a dead step
halts everything visibly, while in a graph one dead branch can disappear into a synthesis that
reads as complete.
