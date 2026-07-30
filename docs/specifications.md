# Fandea Specifications

Normative contracts for the system described in [`architecture.md`](architecture.md).
"MUST", "SHOULD", and "MAY" carry their usual RFC 2119 force.

## 1. Core entities

| Entity | Identity | Mutability |
| --- | --- | --- |
| `Task` | `task_id` (ULID) | Immutable after intake |
| `Run` | `run_id` (ULID) | Append-only status transitions |
| `Attempt` | `(run_id, attempt_no)` | Immutable once closed |
| `Transcript` | content hash | Immutable |
| `Skill` | `skill_id` (slug) | Metadata mutable; versions are not |
| `SkillVersion` | `(skill_id, version)` | **Immutable once written** |
| `ValidationResult` | `(attempt_id, criterion_id)` | Immutable |
| `ReviewDecision` | `decision_id` | Immutable |

The immutability of `SkillVersion` is the load-bearing rule. Evolution MUST produce
version `N+1` with `supersedes: N`; nothing may edit version `N` in place. Rollback is
therefore always available and always cheap.

## 2. Skill schema

Canonical form is JSON at `skills/<skill_id>/v<version>.json`, validated against
[`schema/skill.schema.json`](../schema/skill.schema.json).

```json
{
  "schema_version": "1.0",
  "skill_id": "bump-python-dep",
  "version": 3,
  "supersedes": 2,
  "lifecycle": "approved",
  "title": "Bump a pinned Python dependency and repair fallout",
  "intent": "Raise a pinned dependency to a target version, then fix imports, type errors and test failures caused by the bump.",
  "task_class": "repo-chore",
  "tags": ["python", "dependencies", "lockfile"],
  "parameters": [
    { "name": "package", "type": "string", "required": true },
    { "name": "target_version", "type": "string", "required": false,
      "description": "Omit to take the latest compatible release." }
  ],
  "preconditions": [
    { "kind": "file_exists", "value": "pyproject.toml" },
    { "kind": "command_succeeds", "value": "python -c 'import tomllib'" }
  ],
  "steps": [
    { "id": "locate", "tool": "grep", "intent": "Find the current pin for {{package}}.", "depends_on": [] },
    { "id": "changelog", "tool": "fetch", "intent": "Read the upstream changelog for breaking changes.",
      "depends_on": [], "resources": [{ "kind": "rate_limit", "id": "pypi", "mode": "write" }] },
    { "id": "edit", "tool": "edit_file", "intent": "Raise the pin to {{target_version}}.",
      "depends_on": ["locate"], "resources": [{ "kind": "file", "id": "pyproject.toml", "mode": "write" }] },
    { "id": "sync", "tool": "shell", "intent": "Regenerate the lockfile.", "depends_on": ["edit"] },
    { "id": "repair", "tool": "agent_subtask", "intent": "Fix breakage surfaced by the type checker and tests.",
      "depends_on": ["sync", "changelog"],
      "loop": { "until": "criteria_pass", "max_iterations": 3 } }
  ],
  "success_criteria": [
    { "id": "install", "kind": "command", "run": "uv sync --frozen", "expect_exit": 0, "weight": 1.0 },
    { "id": "types",   "kind": "command", "run": "mypy .",            "expect_exit": 0, "weight": 1.0 },
    { "id": "tests",   "kind": "command", "run": "pytest -q",         "expect_exit": 0, "weight": 1.0 },
    { "id": "scope",   "kind": "judge",   "rubric": "Only dependency-related files changed.",
      "isolation": "fresh_context", "lens": "scope", "weight": 0.3 }
  ],
  "failure_modes": [
    { "symptom": "Transitive pin conflict.", "response": "Relax the narrowest conflicting constraint, then re-run install." }
  ],
  "provenance": {
    "distilled_from_run": "01JD3K...",
    "distilled_at": "2026-07-30T15:22:11Z",
    "evolved_because": "v2 left the lockfile stale when the bump was a no-op."
  },
  "trust": { "applications": 14, "successes": 12, "score": 0.81, "last_used_at": "2026-07-29T09:10:00Z" }
}
```

### 2.1 Field rules

- `success_criteria` MUST contain at least one entry whose `kind` is not `judge`. A skill
  with only model-judged criteria MUST NOT reach `approved`.
- `steps[].loop.max_iterations` MUST be present when `loop` is present. Unbounded step
  loops are invalid.
- `steps[].depends_on` MUST reference existing step ids and MUST form a DAG. A dependency is
  valid only when the step consumes the referenced step's output; ordering-only edges are
  invalid (§26.1).
- `success_criteria[].isolation` MUST be `fresh_context` for `judge` criteria (§26.3).
- `preconditions` are evaluated by `retrieve` **before** a candidate is offered to `plan`.
  A candidate failing any precondition MUST be dropped, not down-ranked.
- `trust.score` is derived, never authored: it is a smoothed success ratio
  `(successes + 1) / (applications + 2)`, so a single lucky application cannot mint a
  high-trust skill. Trust is reported with `lift_estimate`, since a ratio is not causal
  evidence (§19).
- `parameters[].name` MUST match every `{{placeholder}}` used in `steps` and
  `success_criteria`; unbound placeholders are a validation error at store time.
- Required criteria (`weight >= 1.0`) MUST be `preregistered` and carry a valid
  `sensitivity_proof`; otherwise they are treated as advisory regardless of weight (§15).
- `uses` entries MUST pin an exact child version, form an acyclic graph, and stay within
  depth 3 (§14).
- `certification` MUST record the model and tool fingerprint validated against; drift in
  either marks the version `needs_recert` (§20).
- `hygiene.secret_scan` MUST be `passed` before a version may be stored.
- `provenance.curation` MUST be one of `human_authored`, `mined_from_human_artifact`, or
  `self_distilled`, and `self_distilled` versions require the higher evidence bar in §24.
- `contribution` is derived, never authored, and is the retirement input (§24).

### 2.2 Lifecycle values

`draft` → `candidate` → `shadow` → `approved` → `deprecated`, plus `benched`, `needs_recert`,
and terminal `quarantined`.

| State | Retrievable | Notes |
| --- | --- | --- |
| `draft`, `candidate` | No | Awaiting validation or promotion |
| `shadow` | Comparison only | MUST NOT affect the caller's result |
| `approved` **and** in the active set | Yes | The only state eligible for direct application |
| `benched` | No | Retained in full with history; reversible (§24) |
| `needs_recert` | No | Until recertification passes |
| `deprecated`, `quarantined` | No | Terminal |

`benched` is distinct from both `deprecated` (superseded by a newer version) and `quarantined`
(suspected harmful). It means "not currently earning a retrievable slot", and returning to
`approved` requires no new version.

## 3. Graph state

The state object threaded through every node. Nodes return a **delta**, never a mutated
copy, and the orchestrator applies deltas so that every transition is diffable.

```python
class RunState(BaseModel):
    run_id: str
    task: Task
    manifest: RunManifest                   # model, tools, index snapshot, criteria hash, seed
    arm: Literal["treatment", "control", "shadow", "practice"] = "treatment"

    # criteria, locked before solving (§15)
    criteria: list[Criterion] = []          # required set; immutable after intake
    criteria_locked_at: datetime | None = None
    advisory_criteria: list[Criterion] = []

    # retrieval — federated bundle across memory planes (§13)
    bundle: MemoryBundle = MemoryBundle()   # skills, facts, cases, dead_ends, tool_cautions
    chosen: Candidate | None = None
    strategy: Literal["apply", "adapt", "scratch", "portfolio", "decomposition", "abstain"] | None = None
    strategy_reason: str | None = None
    predicted_success: float | None = None  # scored for calibration (§23)

    # solving
    attempt_no: int = 0
    branches: list[Branch] = []             # populated under fan-out strategies (§18)
    artifacts: list[ArtifactRef] = []
    transcript_ref: str | None = None
    workspace_snapshots: list[SnapshotRef] = []
    step_waves: list[list[str]] = []         # step ids executed concurrently, in order (§26.1)
    resource_conflicts: list[ResourceConflict] = []

    # validation
    results: list[CriterionResult] = []     # latest attempt only
    results_history: list[list[CriterionResult]] = []
    merge_audits: list[MergeAudit] = []     # one per fan-in, expected vs received (§26.4)
    failure: FailureVerdict | None = None   # class + evidence (§16)

    # learning
    draft: SkillDraft | None = None
    facts_extracted: list[FactDraft] = []
    affordance_updates: list[AffordanceDelta] = []
    reusability: ReusabilityVerdict | None = None
    written_versions: list[SkillVersionRef] = []

    # control
    budget: Budget
    spent: Spend
    route_log: list[RouteEntry] = []        # (node, decision, reason) — the audit trail
    terminal: Literal["solved", "unsolved", "abstained", "rejected", "error"] | None = None
```

`results_history` exists to make no-progress detection possible: if the newest result
vector equals the previous one, `evolve` MUST NOT route back to `solve`.

`arm` determines measurement handling: `control` runs suppress retrieval (§19), `shadow`
runs MUST NOT affect the caller's result, and `practice` runs MUST be excluded from
user-facing metrics.

## 4. Node contracts

Every node is `(state, services) -> NodeOutput`, where `NodeOutput` carries a state delta,
a route, and a reason string. Nodes MUST be side-effect free with respect to state and MUST
route only to declared successors.

| Node | Preconditions | Postconditions | Legal routes |
| --- | --- | --- | --- |
| `intake` | Request validated | `task` set, budget + model tier resolved, `manifest` recorded, `criteria` locked with hash | `retrieve` |
| `retrieve` | `task` set, criteria locked | `bundle` populated across planes, preconditions evaluated; empty when `arm == "control"` | `plan` |
| `plan` | `bundle` present (possibly empty) | `strategy`, `strategy_reason`, `predicted_success` set | `solve`, `fan_out`, `finalize` (abstain) |
| `fan_out` | `strategy` is `portfolio` or `decomposition` | `branches` created with `kind` set, disjoint workspaces, non-overlapping write claims, and divided budget | `solve` |
| `solve` | `strategy` set, budget not exhausted, clean workspace snapshot taken | Steps executed in `depends_on` order with bounded concurrency (§26.1); `transcript_ref`, `artifacts`, `step_waves` set; `attempt_no` incremented | `validate` |
| `validate` | `transcript_ref` set | `results` set and appended to history; `judge` criteria scored in fresh contexts (§26.3) | `join` |
| `join` | Every dispatched branch has terminated (result, error, or timeout) | `merge_audits` appended; portfolio winner selected by result vector then cost, decomposition inputs reduced then synthesised; losers written to episodic memory | `distill`, `classify_failure` |
| `classify_failure` | Some required criterion failed | `failure` set with class + evidence | `evolve`, `quarantine` |
| `evolve` | Budget remains, progress observed, `failure` set | Repair move applied per §16; workspace restored; a budget decremented | `solve` |
| `distill` | All required criteria passed, `arm != "control"`, task is not an eval fixture | `draft`, `facts_extracted`, `affordance_updates`, `reusability` set | `review`, `finalize` |
| `review` | `draft` reusable | Decision recorded | `store`, `quarantine` |
| `store` | Decision is approve, hygiene scan passed | `written_versions` set; index updated; ledger appended | `finalize` |
| `quarantine` | `failure` set | Failure and dead ends recorded; implicated versions marked suspect | `finalize` |
| `finalize` | — | `terminal` set | — |

### 4.1 Routing predicates

```text
plan     → finalize         : strategy == "abstain"                  (terminal="abstained")
plan     → fan_out          : strategy in {"portfolio", "decomposition"}
join     → distill          : merge_audit.complete
                              AND every criterion with weight >= 1.0 passed
join     → classify_failure : otherwise (including an incomplete merge)
classify → evolve           : spent.attempts < budget.max_attempts
                              AND results != previous results
                              AND failure.class not in {"criteria", "budget"}
classify → quarantine        : otherwise
distill  → review           : reusability.verdict == "reusable"
distill  → finalize         : reusability.verdict == "one_off"   (recorded as evidence)
review   → store            : policy auto-approves OR human approved
review   → quarantine       : human rejected
```

A `criteria` failure class MUST route to `quarantine` with a human escalation flag, never to
`evolve`: the system does not repair its own scorecard (§15).

Criteria with `weight < 1.0` are advisory: they are recorded and surfaced to review, but
they do not block `distill`. This is what keeps `judge` criteria useful without letting a
model's opinion gate promotion.

## 5. Retrieval specification

Retrieval runs per memory plane and returns one `MemoryBundle` (§13.1). For the procedural
plane:

1. **Candidate generation** — union of vector top-`k` (default 20) over `intent` + `title`
   embeddings and lexical top-`k` over title, tags, and step tool names.
2. **Merge** — reciprocal rank fusion, `k=60`.
3. **Filter** — drop any candidate failing a `precondition` (including environment
   fingerprint mismatch), not in the **active set** (§24), in a lifecycle other than
   `approved`/`shadow`, or in a scope not readable by the task.
4. **Rerank** — cross-encoder or model rerank of the top 10 against the task text.
5. **Score floor** — discard candidates below `min_score` (default 0.55). An empty
   candidate list is a valid and healthy outcome.
6. **Evidence and staleness demotion** — multiply score by (a) a low-evidence factor for
   skills below the `evidence_floor`, (b) a decay factor from time since last successful
   application and certification age (§21), and (c) a curation prior favouring
   `human_authored` and `mined_from_human_artifact` over `self_distilled` (§24).

Retrieval MUST NOT hard-drop a candidate for low trust or thin evidence — demotion only.
Hard trust cuts reproduce a measured failure mode in which aggressive exclusion performed
worse than having no library at all (`references.md` §1.2).
7. **Return** — at most 3 candidates with score, matched parameters, and precondition
   evidence attached.

Other planes: facts by hybrid search filtered to readable scope (max 10); cases by vector
similarity over task text (max 3 solved, max 3 dead ends); tool cautions by exact tool
match on the affordance plane.

Rules: when `arm == "control"` retrieval MUST return an empty bundle and record the
suppression (§19). Retrieval MUST be reproducible — the index snapshot id is recorded in the
run manifest, so any eval result ties to an exact memory state. Every bundle element MUST
carry `plane`, `provenance`, and `trust`, since the solver treats them as untrusted evidence
with differing weight (§22).

## 6. Validation specification

Criterion kinds and their contracts:

| Kind | Required fields | Pass condition |
| --- | --- | --- |
| `command` | `run`, `expect_exit` | Process exit code equals `expect_exit` |
| `assertion` | `expr` | Predicate over artifacts evaluates true |
| `schema` | `target`, `schema_ref` | Target validates against schema |
| `metric` | `metric`, `op`, `threshold` | Comparison holds |
| `judge` | `rubric`, `isolation`, `lens` | Model score ≥ 0.7 with recorded justification, evaluated in a fresh context |

Rules: criteria run in a sandbox with the run's workspace mounted; each has its own
timeout (default 300s) counted against `max_wall_clock_s`; a criterion that errors is a
**fail**, not a skip; output is captured (truncated to 32 KiB) and stored with the result.
Model-scored criteria additionally follow the isolation and triangulation rules in §26.3.

Required criteria MUST be locked at `intake` and MUST carry a sensitivity proof; criteria
lacking either property are advisory regardless of declared weight (§15).

## 7. Reusability filter

`distill` computes a `ReusabilityVerdict`. All checks MUST pass for `reusable`:

| Check | Rule |
| --- | --- |
| `parameterisable` | ≥1 extracted parameter, or `task_class` already seen ≥3 times |
| `context_free` | No step depends on a value unavailable outside the originating run |
| `checkable` | ≥1 non-`judge` criterion, and criteria actually executed this run |
| `not_duplicate` | Max cosine similarity to existing approved skills < 0.92, **or** route to `evolve` a new version of the nearest match |
| `bounded` | Every `loop` has `max_iterations` |

A `one_off` verdict is recorded against the task class. When one class accumulates ≥3
`one_off` records, the system MUST surface it for skill authoring — repeated near-misses
are the strongest available signal that a skill is missing.

## 8. Promotion policy

```text
draft      → candidate : all non-judge criteria passed during the originating run
candidate  → shadow    : task_class has an eval set with >= 5 golden tasks
candidate  → approved  : human approval (default in v1)
shadow     → approved  : >= 10 shadow applications
                         AND shadow success >= approved success
                         AND zero golden-set regressions
approved   → deprecated: a newer version of the same skill reaches approved
any        → quarantined: 2 consecutive field failures, or a reviewer rejection
```

Regression gate: before any promotion to `approved`, the golden set for the skill's
`task_class` MUST run green against the candidate. A regression blocks promotion and is
reported with the failing task ids.

## 9. HTTP API

Versioned under `/v1`. JSON only. All mutating calls accept `Idempotency-Key`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/runs` | Submit a task; returns `run_id` (async by default) |
| `GET` | `/v1/runs/{run_id}` | Status, terminal state, route log, spend |
| `GET` | `/v1/runs/{run_id}/transcript` | Structured transcript |
| `POST` | `/v1/runs/{run_id}/cancel` | Cooperative cancel at next node boundary |
| `POST` | `/v1/runs/{run_id}/resume` | Resume from last checkpoint |
| `GET` | `/v1/skills` | List/filter by `task_class`, `lifecycle`, `tag` |
| `GET` | `/v1/skills/{skill_id}/versions/{version}` | Full skill version |
| `POST` | `/v1/skills/search` | Retrieval debug endpoint: scores and drop reasons |
| `GET` | `/v1/reviews?status=pending` | Review queue |
| `POST` | `/v1/reviews/{decision_id}` | `approve` / `reject` / `request_changes` |
| `POST` | `/v1/evals/runs` | Run a golden set against a library snapshot |
| `GET` | `/v1/metrics` | Compounding metrics by task class and snapshot |
| `GET` | `/v1/facts` · `/v1/cases` · `/v1/affordances` | Read the non-procedural memory planes (§13) |
| `POST` | `/v1/memory/query` | Federated retrieval debug across all planes with drop reasons |
| `GET` | `/v1/jobs` · `POST` `/v1/jobs/{job}/run` | Improvement-plane job status and manual trigger (§20) |
| `GET` | `/v1/proposals?status=pending` | Curator, Miner and Correction-miner proposals awaiting review |
| `GET` | `/v1/policy` · `POST` `/v1/policy/proposals` | Read policy config; propose a T2 change, which requires human approval (§22) |
| `GET` | `/v1/ledger/verify` | Verify the integrity chain (§21) |

`POST /v1/skills/search` is not a convenience: retrieval is the primary failure surface,
so its scores and drop reasons must be inspectable without running a task.

Error envelope:

```json
{ "error": { "code": "budget_exhausted", "message": "...", "run_id": "01JD...", "retryable": false } }
```

## 10. CLI

```bash
fandea run "Bump requests to 2.32 and fix fallout"   # submit + stream
fandea run --file task.yaml --budget attempts=6
fandea runs show <run_id> [--route-log] [--transcript]
fandea skills list [--task-class repo-chore] [--lifecycle candidate]
fandea skills show bump-python-dep@3
fandea skills search "dependency bump" --explain      # scores + drop reasons
fandea skills lint                                    # schema + placeholder binding
fandea review queue
fandea review approve <decision_id> --note "..."
fandea eval run --task-class repo-chore --snapshot HEAD
fandea metrics --task-class repo-chore --compare HEAD~5..HEAD

fandea memory query "dependency bump" --planes skills,facts,cases --explain
fandea facts list --scope project
fandea cases show <case_id>                           # includes dead ends
fandea jobs run curator --dry-run                     # proposals only, never promotes
fandea jobs run practice --task-class repo-chore --budget cost=5.00
fandea jobs run recertify --stale-days 30
fandea proposals queue
fandea policy show
fandea policy propose retrieval.min_score=0.60 --eval-compare
fandea ledger verify
fandea lift --task-class repo-chore                   # treatment vs control (§19)
```

## 11. Metrics definitions

Precise definitions, because these numbers decide whether the system works:

| Metric | Definition |
| --- | --- |
| `reuse_rate` | runs with `strategy ∈ {apply, adapt}` ÷ all runs, per task class |
| `first_attempt_success` | runs reaching `distill` with `attempt_no == 1` ÷ all runs |
| `attempts_to_success` | mean `attempt_no` at success; unsolved runs excluded but counted separately |
| `cost_per_solved_task` | Σ `spend.cost_usd` ÷ solved runs |
| `regression_rate` | golden tasks passing on version `N` but failing on `N+1` ÷ golden tasks |
| `retrieval_precision_at_3` | human-labelled applicable candidates in top 3 ÷ 3 |
| `library_yield` | approved skills with ≥1 later application ÷ all approved skills |

`library_yield` is the anti-vanity metric: it goes down when the library grows with
skills nobody reuses.

## 12. Observability

Every node emits a span with `run_id`, `node`, `attempt_no`, `route`, `reason`, and spend
delta. Required structured events: `run.started`, `retrieve.completed` (candidate ids +
scores), `plan.decided` (strategy + reason), `solve.attempt.finished`,
`validate.completed` (result vector), `distill.verdict`, `review.decided`,
`skill.version.written`, `run.finished`.

The `route_log` plus the transcript MUST be sufficient to reconstruct why a run behaved
as it did without re-running a model. Replayability is a hard requirement, not a
debugging nicety: it is what makes the eval harness trustworthy.

Additional required events for the expanded architecture: `criteria.locked` (hash + source),
`failure.classified` (class + evidence), `branch.selected` (winner + margin),
`fact.written`, `case.written`, `proposal.created` (job + kind), `recert.completed`,
`policy.changed` (tier + approver), `ledger.appended`.

Concurrency and merge events, required because a parallel run is otherwise unreadable after
the fact: `step.wave.started` (wave index + step ids + claims held), `resource.conflict`
(claim, blocking step, wait duration), `judge.context.opened` (criterion id + lens + inputs
hash, asserting the solver transcript was not attached), `merge.audited` (expected ids,
received ids, missing ids, action taken).

## 13. Memory plane contracts

### 13.1 MemoryBundle

What `retrieve` returns and `plan`/`solve` consume. Every element carries `plane`,
`provenance`, `trust`, and `score`.

```python
class MemoryBundle(BaseModel):
    skills: list[Candidate] = []        # max 3, procedural plane
    facts: list[FactRef] = []           # max 10, semantic plane
    cases: list[CaseRef] = []           # max 3 solved analogues, episodic plane
    dead_ends: list[CaseRef] = []       # max 3 recorded failures with reasons
    tool_cautions: list[AffordanceRef] = []   # flake rates, error signatures
    suppressed: bool = False            # true on control-arm runs (§19)
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
| Child invalidation propagates | Quarantine or deprecation of a child sets every pinning parent to `needs_recert` |
| `needs_recert` parents are not retrievable as `approved` | Retrieval lifecycle filter (§5) |

Recertification of a parent re-runs its golden set against the child's current approved
version. Passing rewrites the pin to the new child version as a reviewable diff; failing
quarantines the parent.

## 15. Criteria integrity

### 15.1 Locking

`intake` MUST produce the required criteria set and record `sha256` of its canonical
serialisation in the manifest. Sources, in precedence order: caller-declared, skill-inherited
(when a skill is applied), critic-proposed. The critic MUST run in a context that excludes
solver output.

After `criteria_locked_at`, required criteria are immutable. Criteria discovered mid-run enter
`advisory_criteria` with `weight < 1.0` and MAY be promoted to required in the *next* skill
version, never in the current run.

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

## 16. Failure taxonomy

```python
FailureClass = Literal[
    "environment", "tool", "retrieval", "plan", "execution", "criteria", "budget", "merge"
]

class FailureVerdict(BaseModel):
    failure_class: FailureClass
    evidence: list[str]              # criterion ids, tool errors, affordance matches
    implicated_skill: SkillVersionRef | None
    counts_against_trust: bool       # False for environment, tool, budget, merge
    escalate_to_human: bool          # True for criteria
```

| Class | Detection | `evolve` move | Trust impact |
| --- | --- | --- | --- |
| `environment` | Failure before first productive tool call, or setup criterion failed | Repair environment, keep strategy | None |
| `tool` | Error signature matches affordance record, or flake rate above threshold | Retry with backoff, or substitute tool | None |
| `retrieval` | Applied skill's preconditions passed but its steps were inapplicable | Drop candidate, re-retrieve, propose tighter preconditions | Yes, on the skill |
| `plan` | Required criteria failed with no partial progress | Switch strategy, escalate model tier | Yes, if a skill was applied |
| `execution` | Partial progress with specific criterion failures | Patch artifacts using criterion output | Yes |
| `criteria` | Criteria unsatisfiable, mutually contradictory, or sensitivity proof invalid | **None** — halt | None |
| `budget` | Any budget exhausted | **None** — halt | None |
| `merge` | A merge audit reported missing inputs, or a resource claim deadlocked (§26.2, §26.4) | Re-dispatch only the missing branches or steps once, from their retained snapshot; a deadlock re-runs the cycle serially | None |

`merge` exists as its own class because the repair is narrow — rerun the piece that never
arrived — and because charging trust for a branch that died in the executor would let
infrastructure noise demote working skills. A second consecutive `merge` verdict on the same
run halts rather than retrying, and files the loss as evidence against the skill's step
graph rather than its content.

Misclassification is itself a tracked defect: a `retrieval` verdict that recurs on the same
skill MUST trigger a Curator proposal to tighten that skill's preconditions, and a `merge`
verdict that recurs on the same skill MUST trigger a Curator proposal to serialise the
implicated steps.

## 17. Attempt isolation

| Rule | Detail |
| --- | --- |
| Snapshot before attempt | `solve` MUST run against a snapshot taken before its first mutation |
| Restore before retry | `evolve` MUST restore the pre-attempt snapshot; retrying on a dirty workspace is invalid |
| Disjoint branch workspaces | `fan_out` clones per branch; branches MUST NOT share a mutable workspace |
| Concurrent step isolation | Steps in the same wave share the attempt's workspace, so their write claims MUST be disjoint (§26.2); a wave is atomic for restore purposes — `evolve` rolls back the whole wave, never half of it |
| Verifier isolation | A `judge` criterion's context is built from artifacts and the criterion text alone; it MUST NOT inherit the solver's transcript (§26.3) |
| Snapshot retention | Retained for the run's lifetime plus the eval retention window, then garbage-collected |
| External effects | `external`-class tool calls are recorded with a compensating action where one exists |
| Uncompensable effects | A skill containing an uncompensable `external` step MUST NOT run in `portfolio` or `shadow` mode |

## 18. Fan-out: portfolio and decomposition

```python
class Branch(BaseModel):
    branch_id: str
    kind: Literal["portfolio", "decomposition"] = "portfolio"
    strategy: Literal["apply", "adapt", "scratch"]
    subtask: str | None = None     # decomposition only: the part of the work owned
    candidate: Candidate | None
    workspace_ref: str
    resources: list[ResourceClaim] = []
    budget: Budget                 # a division of the parent budget, never a multiple
    results: list[CriterionResult] = []
    selected: bool = False
    margin: float | None = None    # winner score minus runner-up
```

Two kinds with different join semantics:

| Kind | Branches | Join | Failure of one branch |
| --- | --- | --- | --- |
| `portfolio` | Competing strategies for the same task | Select one winner | Tolerated; remaining branches still adjudicate |
| `decomposition` | Disjoint parts of the work | All must complete, then synthesise | Blocks synthesis; recorded in the merge audit (§26.4) |

`plan` MAY choose `decomposition` only when the locked criteria can be partitioned: every
branch owns a subset of the required criteria, the subsets are disjoint, and their union is
the full required set. A criterion that no branch owns is a criterion nothing is accountable
for, which is how a decomposed run reports success while missing a requirement. Criteria that
can only be scored on the merged artifact stay with the join and are evaluated after
synthesis; if any exists, the join MUST NOT route to `distill` before scoring them.

Rules: `max_branches` default 3; the parent budget is divided, so fan-out trades latency for
cost-neutral exploration; branches MUST hold disjoint workspaces **and** non-overlapping `write`
or `exclusive` resource claims (§26.2); `join` selects by required-criteria pass count, then by
advisory score, then by lowest cost — a model preference MUST NOT break a tie; losing portfolio
branches are written to the episodic plane as cases, because a validated comparison between
approaches is exactly the evidence the Curator and Practice jobs need.

## 19. Ablation and eval integrity

| Rule | Detail |
| --- | --- |
| Control sampling | `ablation_rate` (default 0.05), stratified by task class, assigned at `intake` |
| Control behaviour | `retrieve` returns an empty bundle with `suppressed = True`; the run is otherwise identical |
| Exclusions | Never sample tasks with `external` side effects, explicit user-supplied skills, or eval fixtures |
| Rate governance | `ablation_rate` is T3 — the system cannot shrink its own control arm (§22) |
| Eval firewall | Runs whose task is an eval fixture MUST be blocked at `distill` |
| Golden provenance | A golden fixture MUST NOT be created from a run that produced a stored skill |

`causal_lift` for a task class over a window:

```text
causal_lift = first_attempt_success(treatment) - first_attempt_success(control)
```

Reported with a Wilson confidence interval and sample counts. A lift claim whose interval
includes zero MUST be reported as "not established" rather than as an improvement.

## 20. Improvement job contracts

Every job: reads memory and the run store, writes **only** proposals, and is budgeted.

| Job | Trigger | Emits | Hard rule |
| --- | --- | --- | --- |
| `miner` | Manual, or on repository connect | `draft` skills and facts from history, PRs, CI config, runbooks | Mined skills MUST be validated before promotion; merged history is evidence, not certification |
| `curator` | Scheduled, or on library-size or precision-decay trigger | Active-set recomputation, retirement, extract-child, split, tighten-precondition, merge, compact, **parallelise**, and **serialise** proposals | Every proposal MUST pass the golden-set regression gate; retirement MUST respect the evidence floor (§24.3) |
| `practice` | Scheduled, or ≥3 one-offs in a class | Practice runs marked `arm="practice"` | Excluded from user-facing metrics; separate budget |
| `recertifier` | Schedule, model upgrade, tool version change, child invalidation | Recert results; `needs_recert` / `quarantined` transitions | MUST re-run sensitivity proofs, not just criteria; MUST re-derive resource claims when a tool's registry entry changes |
| `correction_miner` | ≥N reviewer edits accumulated | Distiller-guidance and criteria-template proposals (T2) | MUST NOT self-apply; human approval plus eval comparison required |

Practice task selection targets estimated success probability in `[0.2, 0.8]`, using
`predicted_success` calibrated against outcomes: outside that band an attempt yields little
information, which is the whole point of a curriculum.

The two step-graph proposals are the Curator's half of the concurrency story, and both must
argue from run evidence rather than from reading the skill:

| Proposal | Evidence required | Effect |
| --- | --- | --- |
| `parallelise` | A `depends_on` edge that failed the fake-edge test (§26.1) across ≥5 runs: the later step never read the earlier step's output, and their claims do not overlap | Removes the edge, producing a new skill version |
| `serialise` | ≥2 `merge` verdicts or a resource conflict rate above `conflict_threshold` (default 0.1) on the same wave | Adds an edge or widens a claim to `exclusive`, producing a new skill version |

Both go through the normal promotion gate, so a wrongly removed edge shows up as a golden-set
regression before it reaches a user's run. A `serialise` proposal MUST NOT be blocked on the
latency regression it causes: correctness outranks the parallelism metric.

## 21. Provenance ledger

```python
class LedgerEntry(BaseModel):
    seq: int
    prev_hash: str
    entry_hash: str            # sha256 over canonical entry minus entry_hash
    actor: str                 # run id, job name, or human id
    action: Literal["write", "promote", "quarantine", "deprecate", "policy_change"]
    target: str                # skill version, fact id, policy version
    evidence: dict             # criteria results, eval ids, approver
    at: datetime
```

`GET /v1/ledger/verify` recomputes the chain. Because the system writes its own memory,
"who wrote this and on what evidence" must be tamper-evident rather than merely logged.

## 22. Governance of mutable surfaces

Every mutable surface carries a tier (see [ADR-0005](adr/0005-self-modification-boundary.md)).

| Tier | Surfaces | Write path |
| --- | --- | --- |
| T0 | Trust scores, affordance aggregates, cases, retrieval caches | Runs write directly; derived and rebuildable |
| T1 | Skill and fact versions, curator proposals, shadow promotions | Promotion policy with eval evidence and zero regressions |
| T2 | Authoring prior, distiller guidance, criteria templates, retrieval thresholds, routing ladder, budget defaults, values of `active_cap` / `retirement_threshold` / `evidence_floor` / `max_parallel_steps` / `conflict_threshold` / `layer_threshold` | Versioned config, human approval, eval comparison |
| T3 | Tool registry with side-effect classes **and declared resource claims**, sandbox policy, promotion thresholds, ablation rate, graph topology, judge-isolation and merge-audit enforcement, finiteness of the active cap and retirement threshold, tier assignments | Code or config review only; unreachable from run and job code paths |

Enforcement requirements:

- T3 surfaces MUST be unreachable from any module a run or job can import; asserted by a CI
  import-boundary test, not by convention.
- A write to a T2 surface without a recorded human approver MUST fail closed.
- Any new mutable surface MUST be assigned a tier; an untiered surface is a review blocker.
- Retrieval and prompt content MUST NOT be able to alter a tier assignment — memory is data,
  never instructions (§13.1, and the injection control in `architecture.md` §15.2).

## 23. Additional metrics

| Metric | Definition |
| --- | --- |
| `causal_lift` | Treatment minus control `first_attempt_success`, with Wilson interval (§19) |
| `calibration_error` | Brier score of `predicted_success` against outcome |
| `abstention_precision` | Abstentions later confirmed unsolvable or human-escalated ÷ all abstentions |
| `recert_pass_rate` | Skills passing scheduled recertification ÷ skills recertified |
| `retrieval_decay` | Change in `retrieval_precision_at_3` per 100 skills added |
| `mean_composition_depth` | Mean `uses` depth of applied skills; rising means abstraction is happening |
| `dead_end_avoidance` | Runs where a retrieved dead end suppressed a repeated approach ÷ runs with dead ends retrieved |
| `curator_yield` | Curator proposals approved ÷ proposals raised |
| `fact_contradiction_rate` | Open contradictions ÷ total facts |
| `practice_conversion` | Practice runs producing an approved skill ÷ practice runs |

`retrieval_decay` is the early-warning metric for library entropy: it turns negative before
`first_attempt_success` does, which is what gives the Curator time to act.

| Metric | Definition |
| --- | --- |
| `skill_contribution` | Per-skill `ĉ(s)`: mean first-attempt success when applied, minus the control-arm baseline for its task class (§24) |
| `active_cap_pressure` | Task classes at `active_cap` ÷ task classes with skills |
| `retirement_reversal_rate` | Benched versions later restored to `approved` ÷ versions benched |
| `curation_gap` | First-attempt success of `human_authored` + `mined_from_human_artifact` skills minus `self_distilled` skills, per task class |

`curation_gap` exists to test a specific external finding in our own domain (`references.md`
§1.1). If it is near zero here, the higher evidence bar on self-distilled skills should be
relaxed; if it reproduces, the Miner deserves more investment than the distiller.

Concurrency and verification integrity:

| Metric | Definition |
| --- | --- |
| `merge_gap_rate` | Merge audits with missing inputs ÷ merge audits — the rate at which work is dispatched and silently lost; target zero |
| `merge_recovery_rate` | Incomplete merges resolved by re-dispatch ÷ incomplete merges |
| `resource_conflict_rate` | Step waves that blocked on a claim ÷ waves with ≥2 steps |
| `parallel_speedup` | Serial step duration ÷ observed wall-clock duration per skill; the only justification for step DAGs, so it is reported per skill, not in aggregate |
| `fake_edge_rate` | `depends_on` edges failing the fake-edge test ÷ declared edges — a measure of how conservatively the distiller writes graphs |
| `judge_isolation_violations` | Judge invocations whose context hash included solver-transcript content; a non-zero value is a release blocker, not a metric to trend |

`parallel_speedup` and `merge_gap_rate` are read together or not at all. Speedup with a
non-zero gap rate is not speed, it is a system that finishes early by dropping work.

## 24. Library capacity and retirement

Contracts implementing [ADR-0006](adr/0006-bounded-library-and-retirement.md).

### 24.1 Active set

| Rule | Detail |
| --- | --- |
| Retrievability | Only skills in the active set are retrievable for application |
| Cap | `active_cap` per task class, default 50; MUST be finite |
| Selection | Rank `approved` versions by `contribution`, then `trust.decayed_score`, then recency; the top `active_cap` are `active` |
| Overflow | Versions outside the cap become `benched`, not deleted |
| Re-evaluation | The Curator recomputes the active set on schedule and after any promotion |
| Newly approved skills | Enter active with a protected grace period of `evidence_floor` applications, so a new skill is not benched before it can be measured |

The grace period matters: without it, a cap plus a contribution ranking would permanently favour
incumbents, and no new skill could ever accumulate the evidence needed to displace one.

### 24.2 Contribution estimate

```python
class Contribution(BaseModel):
    skill_id: str
    version: int
    applications: int                 # trials counted toward the evidence floor
    successes: int
    baseline_success: float           # control-arm first-attempt success for the task class
    estimate: float                   # ĉ(s) = successes/applications - baseline_success
    interval: tuple[float, float]     # Wilson interval on the difference
    last_evaluated_at: datetime
```

Rules: only `treatment`-arm applications count toward `applications`; `environment`, `tool`, and
`budget` failure classes are excluded from the denominator (§16); `baseline_success` comes from
the ablation arm (§19), and when a task class has no control samples, contribution is `null` and
the skill MUST NOT be retired on contribution grounds.

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

Contracts for the graph-execution rules in `architecture.md` §5.6, §5.10 and §6.1. Sourced from
the practitioner account in [`references.md`](references.md) §1.7.

### 26.1 Step dependency graphs

| Rule | Detail |
| --- | --- |
| Declaration | Every step declares `depends_on`; an empty list means no predecessor is required |
| Validity | An edge is valid only if the step consumes the referenced step's output. Ordering-only edges MUST be removed, not declared |
| Structure | The step graph MUST be acyclic and all referenced ids MUST exist; both checked at store time |
| Execution | Steps whose dependencies are satisfied run concurrently, subject to §26.2 |
| Authoring | The authoring prior (§25.1) instructs the distiller to emit only data-carrying edges |
| Curation | The Curator MAY propose removing an edge; such a proposal MUST show that the dependent step's output is unchanged when the edge is dropped |

Concurrency is bounded by `max_parallel_steps` (default 8) so a wide skill cannot exhaust
tool-runtime capacity.

Execution proceeds in **waves**: the scheduler takes all steps whose dependencies are
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
| Effect | Conflicting units MUST NOT run concurrently, even with no `depends_on` between them and even in separate workspaces |
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
| Standing limit | Judges remain advisory: promotion still requires a non-`judge` criterion (§2.1) |

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
