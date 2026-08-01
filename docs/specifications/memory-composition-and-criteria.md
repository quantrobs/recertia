# Fandea Specifications: 13. Memory plane contracts

## 13. Memory plane contracts

### 13.1 MemoryBundle

What `retrieve` returns and `plan`/`solve` consume. Every element carries `plane`,
`provenance`, `trust`, and `score`.

```python
class MemoryBundle(BaseModel):
    skills: list[SkillCandidateRef] = []      # max 3, procedural plane
    facts: list[MemoryElementRef] = []        # max 10, semantic plane
    cases: list[MemoryElementRef] = []        # max 3 solved analogues, episodic plane
    dead_ends: list[MemoryElementRef] = []    # max 3 recorded failures with reasons
    tool_cautions: list[MemoryElementRef] = []  # flake rates, error signatures
    suppressed: bool = False                  # true on control-arm runs (§19)
```

### 13.2 Fact record (semantic plane)

Canonical at `facts/<scope>/<slug>.json`.

| Field | Rule |
| --- | --- |
| `fact_id`, `scope`, `statement` | `statement` is a single assertion, not a procedure |
| `verification` | Optional check that re-establishes the fact; a fact with one is `verified`, without one is `asserted` |
| `provenance` | Run, job, or human that asserted it, plus evidence reference |
| `confidence` | Derived from verification recency and contradiction count |
| `contradicts` | Ids of facts this one conflicts with |

A contradiction MUST NOT be silently resolved: both facts are retained, both are demoted in
confidence, and the conflict is queued for review. Silent resolution would let the system
overwrite true knowledge with a plausible mistake.

### 13.3 Case record (episodic plane)

Written for **every** attempt, successful or not. Immutable, content-addressed.

| Field | Rule |
| --- | --- |
| `case_id`, `run_id`, `attempt_no` | — |
| `outcome` | `solved` \| `failed` \| `abandoned` |
| `failure_class` | Required when `outcome != "solved"` (§16) |
| `dead_end` | `{ approach, why_failed, evidence_ref }` — required when `outcome == "failed"` |
| `transcript_ref`, `artifacts` | Content hashes |
| `distilled_into` | Skill version, when the case produced one |

Dead ends are retrieved by `evolve` and MUST suppress re-selection of an approach whose
recorded `why_failed` still applies in the current environment.

### 13.4 Affordance record

Derived aggregates per tool and environment: invocation count, failure rate, known error
signatures with suggested responses, flake rate, p50/p95 duration, mean cost. Rebuildable
from the run store, so it is T0 (§22) and never reviewed.

The plane also aggregates **contention** observed through resource claims (§26.2): median
and p95 wait time per claimed resource, conflict rate, and observed concurrency ceiling for
rate-limited services. `fan_out` MUST read the ceiling before dispatching branches that
claim the same `rate_limit` resource, and `plan` MUST prefer a sequential strategy when the
observed ceiling is 1. This is how a rate limit discovered the hard way becomes a scheduling
constraint rather than a recurring failure.

`plan` and `evolve` MUST consult flake rate before classifying a failure as `execution`:
a known-flaky tool produces `tool`, which does not damage skill trust (§16).

### 13.5 Policy record

A single versioned document holding model tier per task class, escalation ladder, budget
defaults, retrieval thresholds (`min_score`, `min_trust`, decay), ablation rate, and
promotion thresholds. Fields are tagged with their governance tier; a write attempt to a T3
field MUST fail closed regardless of caller (§22).

## 14. Composite skills

A skill MAY declare `uses: [{skill_id, version}]` and invoke a child as a step.

| Rule | Enforcement |
| --- | --- |
| Children are pinned to an exact version | Store-time validation; unpinned reference is invalid |
| The `uses` graph is acyclic | Cycle detection at store time |
| Depth ≤ 3 | Store-time validation |
| A parent's criteria MUST cover the composed outcome | Parent needs ≥1 required criterion of its own, not only inherited ones |
| Child invalidation propagates | Marking a child `quarantined` (§2.5, §20) or `deprecated` sets every pinning parent to `needs_recert` |
| `needs_recert` parents are not retrievable as `approved` | Retrieval lifecycle filter (§5) |

Recertification of a parent re-runs its golden set against the child's current approved
version. Passing rewrites the pin to the new child version as a reviewable diff; failing
quarantines the parent.

## 15. Criteria integrity

### 15.1 Locking

`intake` MUST produce the required `TaskCriterion` set and record `sha256` of its canonical
serialisation in the manifest. Sources, in precedence order: caller-declared,
task-class-template, critic-proposed. **No skill is a valid source** — `intake` runs before
`retrieve` and `plan`, so no skill has been chosen yet; `contracts/criteria.py`'s
`TaskCriterion.source` is typed to exclude it entirely. The critic MUST run in a context that
excludes solver output.

After `criteria_locked_at`, the `TaskCriterion` set is immutable **and is never modified by
which skill `plan` subsequently chooses** — see §15.4 and the
[ADR-0003 amendment](../adr/0003-criteria-preregistration.md#amendment-two-criteria-timelines-2026-07-30).
Criteria discovered mid-run enter `advisory_criteria` with `weight < 1.0` and MAY be promoted to
required in the *next* skill version, never in the current run.

### 15.2 Sensitivity proofs

```python
class SensitivityProof(BaseModel):
    criterion_id: str
    negative_fixture: str          # pre-solve workspace, mutant, or recorded failure case
    rejected: bool                 # criterion MUST evaluate to fail on the fixture
    checked_at: datetime
    checked_against: str           # manifest hash of the environment used
```

Rules: a criterion without `rejected == True` is advisory only; a skill MUST have ≥1 required
criterion with a valid proof to reach `candidate`; proofs are re-run during recertification,
because a criterion can become vacuous when the environment changes.

### 15.3 Criteria change rules

Criteria are versioned with the skill. A new version that removes a required criterion, or
lowers one below `weight 1.0`, MUST be flagged `criteria_weakened` in the review queue and MUST
run the prior version's criteria as part of the regression gate. This makes weakening possible
when justified, and impossible to do quietly.

### 15.4 Two criteria timelines (`TaskCriterion` vs. `SkillCertificationCriterion`)

Two different questions, two different types, two different timelines — resolved per
[the ADR-0003 amendment](../adr/0003-criteria-preregistration.md#amendment-two-criteria-timelines-2026-07-30)
(refactor-plan B2):

| | `TaskCriterion` | `SkillCertificationCriterion` |
| --- | --- | --- |
| Answers | Did this run solve what the caller asked for? | Does this skill version reliably do what it claims? |
| Authored | At `intake`, before a skill is chosen | At `distill`, from the transcript that produced the draft |
| "Preregistered" means | Locked before `solve` | Locked before the *certification runs* (shadow trials, scheduled recertifications, §8/§20) that validate it — not before the transcript |
| Lives on | `RunState.criteria` (§3) | `SkillVersion.certification_criteria` (§2.1) |
| Enters a run's required set? | Yes, always | **Never** |

A skill's certification criteria MAY additionally be scored against the *same run's* artifact —
the artifact already exists, so this is free — but the result lands in
`RunState.certification_observations` (§3), which is advisory telemetry for `SkillStats` and
`needs_recert` triggers and **MUST NOT** gate `join`, `distill`, or the caller's result. This is
the rule that keeps the reopened Goodhart path closed: a caller cannot be told a task "solved"
against a bar chosen after the fact by which skill happened to be retrieved.
