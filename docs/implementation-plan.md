# Fandea Implementation Plan

Build order for the system in [`architecture.md`](architecture.md) against the contracts in
[`specifications.md`](specifications.md). Milestones are sequenced by dependency and by what
each one lets you *measure*, not by calendar time.

## Guiding sequencing rules

1. **Close the loop before widening it.** A narrow loop that provably compounds on one task
   class is worth more than a broad system whose improvement cannot be demonstrated.
2. **Measurement integrity precedes autonomy.** Criteria locking, sensitivity proofs, the eval
   firewall, and the ablation arm all land before anything promotes itself. Autonomy granted on
   untrustworthy metrics is unrecoverable, because the evidence needed to detect the problem is
   the thing that is broken.
3. **Governance boundaries are structural, not retrofitted.** The T0–T3 module boundary
   (specs §22) is enforced from M0, since separating it later means auditing every call
   path that already exists.
4. **Curation is not a late-stage nicety.** The one field-wide finding we have says lifecycle
   management, not skill authoring, is the bottleneck — self-generated skills measured +0.0pp
   against a no-skill baseline while managed libraries produced large gains
   ([`references.md`](references.md) §1.1). The authoring prior lands with the distiller in M3, and
   capacity plus retirement land in M5 alongside the first autonomy.

## Technology stack

Literature grounding for the sequencing choices, including the findings that changed the design,
is in [`references.md`](references.md).

| Layer | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.12 | Tooling and model-SDK ecosystem |
| Packaging | `uv` + `pyproject.toml` | Fast, lockfile-based |
| Contracts | Pydantic v2 | Runtime validation of graph state and memory documents |
| API | FastAPI + Uvicorn | Matches Pydantic models |
| Persistence | SQLite (`sqlite-vec`, FTS5) → Postgres (`pgvector`) | Driver-swap upgrade path |
| Canonical memory | JSON in git: `skills/`, `facts/`, `policy/` | Review = pull request; rollback = revert |
| Workspaces | Git worktrees or overlay copies, content-addressed snapshots | Per-attempt isolation (specs §17) |
| Job scheduling | APScheduler in v1 → external scheduler | Improvement plane jobs (specs §20) |
| Sandbox | Subprocess with rlimits in v1; container isolation before any non-`read` tool ships | |
| Tests | `pytest`, `pytest-asyncio`, `hypothesis` for state-machine invariants | |
| Lint/type | `ruff`, `mypy --strict` on `src/` | |
| Tracing | OpenTelemetry → local collector | |

## Repository layout

Per [ADR-0009](adr/0009-contracts-as-code.md), `contracts/` (Pydantic models, generated
`schema/`, semantic profiles) exists ahead of `src/fandea/` — specification tooling, not the
runtime. `src/fandea/` imports from it rather than redefining these types.

```text
fandea/
├── pyproject.toml
├── contracts/                  # normative structural source (ADR-0009); Pydantic models
├── schema/                     # JSON Schema, generated from contracts/ — never hand-edited
├── skills/<skill_id>/v<N>/     # version.json (immutable, git), status.json, stats.json (ADR-0007)
├── facts/<scope>/<slug>.json       # semantic memory, canonical
├── policy/                          # T2 config, versioned and reviewed
├── src/fandea/
│   ├── graph/                 # engine: registry, router, checkpoints, budgets, fan-out
│   ├── nodes/                 # intake, retrieve, plan, fan_out, solve, validate, join,
│   │                          # classify_failure, evolve, distill, review, store,
│   │                          # record_dead_end, reject_draft, finalize (ADR-0008)
│   ├── memory/
│   │   ├── procedural/        # skills: store, versioning, lineage, composition, git adapter
│   │   ├── semantic/          # facts: assertions, verification, contradictions
│   │   ├── episodic/          # cases and dead ends
│   │   ├── affordance/        # tool + environment telemetry aggregates
│   │   └── policy/            # policy document access (read-only to runs)
│   ├── retrieval/             # per-plane search, fusion, rerank, preconditions, decay
│   ├── solver/                # model client, tool runtime, transcript writer
│   ├── validation/            # criterion runners, sensitivity proofs, sandbox
│   ├── distill/               # generalisation, fact extraction, reusability filter, hygiene
│   ├── review/                # lifecycle, promotion policy, trust, calibration
│   ├── workspace/             # snapshot, restore, clone, compensation
│   ├── jobs/                  # miner, curator, practice, recertifier, correction_miner
│   ├── evals/                 # golden sets, harness, ablation, metrics
│   ├── ledger/                # hash-chained provenance
│   ├── governance/            # tier registry + enforcement (T3: not importable by runs/jobs)
│   ├── store/                 # SQLite/Postgres adapters, migrations
│   ├── api/                   # FastAPI app
│   └── cli/                   # typer app
├── evals/golden/<task_class>/ # golden fixtures — never distilled from
├── docs/
└── tests/{unit,property,replay,e2e,boundary}
```

## M0 — Walking skeleton with integrity rails

**Goal:** one task traverses the whole graph with no learning, no models, no memory — but with
the rails that everything later depends on.

Per refactor-plan B6, four mechanisms that the original plan deferred past the point their own
MUSTs require them are pulled forward here, at the *minimum* strength each needs — not their
full eventual form:

- Graph engine: node registry, typed `RunState` (from [`contracts/run.py`](../contracts/run.py)),
  conditional edges from the route table in [`contracts/graph.py`](../contracts/graph.py),
  per-node checkpoints, budget accounting enforced on back-edges.
- **Stable operation ids and at-least-once execution.** Every side-effecting node call (tool
  invocation, ledger append) is keyed by `(run_id, attempt_no, node, op_seq)`; a resumed run
  replays or no-ops already-applied operations rather than re-executing them. Without this,
  "killing the process mid-run and resuming completes it" (below) is a claim with no mechanism.
- All fifteen nodes stubbed per `specifications.md` §4 (`join` is a no-op stub — it only
  activates once `fan_out` exists in M6); `solve` is a scripted tool sequence.
- `validate` runs `command` criteria for real in the subprocess sandbox.
- **Criteria locking** at `intake` with hash recorded in the run manifest; `TaskCriterion` only
  (§15.1 — no skill has been chosen at `intake`).
- **Minimal sensitivity-proof execution.** `validate` checks that every required criterion's
  `sensitivity_proof.rejected == true` before counting it toward a pass; M0's golden fixture
  ships hand-authored proofs. This is the *check*, not the authoring tooling (that is M3) — but
  without it, every "required" criterion in M0–M2 is definitionally advisory per §2.4, and every
  later milestone's done-when that assumes required criteria matter would be unverifiable.
- **Attempt isolation:** workspace snapshot before each attempt, restore in `evolve`.
- **Failure classification** with the eight-class taxonomy and explicit `FailureSignal`
  (ADR-0008), driving `evolve` move selection.
- **Ledger:** append-only hash chain with `verify`.
- **Governance skeleton:** tier registry plus a CI import-boundary test proving `nodes/` and
  `jobs/` cannot import `governance/` or `evals/ablation`.
- CLI `fandea run`, `fandea runs show --route-log`, `fandea ledger verify`.

**Done when:** a run reaches `finalize` with `terminal="solved"`; killing the process mid-run
and resuming completes it from the last checkpoint with no operation double-applied (proven by
the stable-operation-id mechanism, not asserted); a run whose criteria always fail terminates
at `record_dead_end` with a failure class rather than looping; retrying always starts from a
clean snapshot; a required criterion with no sensitivity proof is treated as advisory, not
required, and this is visible in the route log; the boundary test fails if a node imports a T3
module.

## M1 — Procedural memory and retrieval

**Goal:** hand-authored skills are found and applied. No distillation yet.

Per refactor-plan B6, two more mechanisms are pulled forward: a stub active-set assignment (so
retrieval's active-set filter is not a silent no-op), and a minimal golden-regression runner (so
approving the seed library does not quietly bypass the regression gate specs §8 requires of
every promotion).

- Structural validation against `schema/skill_version.schema.json` (generated from
  [`contracts/skill.py`](../contracts/skill.py)) plus the `candidate-skill` /
  `approved-skill` semantic profiles from [`contracts/profiles.py`](../contracts/profiles.py),
  including placeholder binding and `uses` validation.
- Skill store with immutability guard (any write to an existing version is refused), lineage,
  and git adapter, writing `SkillVersion` (git) separately from `SkillStatus` (ADR-0007).
- **Active-set stub.** Every `approved` `SkillStatus.active` is `True` by default — no cap, no
  ranking, no eviction yet (those are M5) — but the *filter* retrieval applies (§5, §24.1) is the
  real mechanism from day one, so M5 tightens a working gate instead of installing the first one.
- **Golden-regression runner (minimal).** One golden task per seed skill, run before that skill's
  `SkillStatus.lifecycle` is set to `approved`. The full harness (fixtures per task class,
  snapshot pinning, `causal_lift`) is M4; this is the narrow slice specs §8's regression gate
  needs to be true of the seed library specifically, so "approving the seed library" is not a
  documented exception to a rule that does not exist yet.
- Index build from canonical files with snapshot ids; embeddings + FTS5.
- Retrieval pipeline: generation, RRF merge, precondition filter including environment
  fingerprint, active-set filter, rerank, score floor, evidence and staleness demotion.
- `plan` chooses `apply` / `adapt` / `scratch` / `abstain` with `predicted_success`.
- 8–12 hand-authored `repo-chore` skills, marked `curation: human_authored`, each with hygiene
  scan run and a hand-authored sensitivity proof per required criterion (both structural
  prerequisites from M0, applied here to real content for the first time).
- `fandea skills lint`, `fandea skills search --explain`.

**Done when:** `retrieval_precision_at_3` ≥ 0.7 on a labelled probe set; unrelated tasks return
an empty bundle; novel tasks route to `scratch`; a skill whose environment fingerprint does not
match is dropped rather than down-ranked; a thin-evidence skill is demoted in ranking but never
hard-dropped; every seed skill passed its golden task before reaching `approved`, and the
regression runner's log is the evidence, not a note in a PR description.

## M2 — Solver, tool runtime, episodic and affordance memory

**Goal:** real model-driven solving that produces distillable transcripts and remembers failures.

- Model client with retry, timeout, token and cost accounting.
- Tool registry with side-effect classes, **resource claims**, and approval hooks; tools for the
  first domain. Claims cover files, paths, services, rate limits, locks, and external systems, so
  hidden edges are declared rather than discovered under load.
- Structured transcript writer, content-addressed.
- Skill application: parameter binding, **dependency-ordered step execution** with concurrency for
  independent steps, resource-claim serialisation, `steps[].loop` bounds, `max_parallel_steps`.
- **Wave recording:** every concurrent batch written to `step_waves` with its snapshot, since a
  transcript cannot show what ran together and a parallel attempt must stay replayable. Rollback
  is per wave, never per step.
- **Claim scheduling:** fixed acquisition order, `claim_timeout_s`, and a timeout that produces a
  `merge` verdict re-running the wave serially rather than an uninterpretable hang.
- **Episodic writes for every attempt**, including `dead_end` records with reasons.
- **Affordance telemetry:** durations, error signatures, flake rates, and contention per claimed
  resource, so an observed concurrency ceiling of one becomes a scheduling constraint.
- `evolve` implements all repair moves from specs §16, consults dead ends to avoid repeats, and
  short-circuits on identical result vectors.

**Done when:** golden `repo-chore` tasks are solved end-to-end via applied skills; a task that
previously failed a given way does not repeat that approach; a known-flaky tool produces a
`tool` classification that leaves skill trust untouched; two independent steps demonstrably run
concurrently while two steps claiming the same `write` resource serialise; a wave that fails
mid-flight restores whole rather than leaving a half-applied state; replay tests reconstruct node
decisions, including wave composition, with no model calls.

## M3 — Distillation, facts, review

**Goal:** the loop closes. Successful runs produce reviewed memory.

- Critic pass proposing criteria pre-solve when the caller supplies none.
- **Verifier isolation:** `judge` criteria evaluated in a fresh context holding only the artifact
  and rubric, with distinct `lens` values across judges, and the isolation mode plus a hash of the
  exact context recorded per result. The hash is what turns "judges are isolated" from an
  assertion in a document into something a test can prove.
- **Sensitivity-proof authoring tooling**, generating proofs automatically per criterion; M0
  only *checked* proofs that already existed by hand, this is what authors them at scale.
  Unproven criteria remain advisory.
- **Golden-regression harness, generalised.** The M1 one-task-per-skill runner is extended to a
  full harness per task class; `review`'s approval path calls the same runner M1 introduced,
  not a parallel mechanism, so "reviewer approves a candidate" and "seed skill reaches approved"
  are the same rule applied at different points in the library's history.
- **Authoring prior** as a versioned T2 document, applied on every distillation, with
  `authoring_prior_version` recorded on each skill. This lands here rather than later because it
  was the highest-value single component in the only ablation that measured it
  ([`references.md`](references.md) §1.3).
- Distiller success path: parameter extraction, generalisation, pruning, criteria proposal,
  **fact extraction**.
- **Failure-cluster path:** cluster episodic dead ends by task class and failure signature, author
  pitfall-oriented skills at ≥3 distinct runs, using the cluster as the negative fixture.
- Reusability filter, `one_off` recording per task class, near-duplicate routing to a new
  version of the nearest skill.
- Fact store with verification, confidence, and contradiction retention.
- Hygiene scan at store time; failing drafts rejected. `curation` provenance recorded.
- Review service, queue, decisions; `store` writes transactionally and appends to the ledger.

**Done when:** a novel task solved from scratch yields a `candidate` skill a reviewer approves,
and a later similar task retrieves and applies it with `attempt_no == 1`. That transition is the
system's core claim. Also: a deliberately vacuous criterion is rejected by its sensitivity
check, a draft containing a planted secret is refused, a repeated failure signature produces
a pitfall skill whose criteria fail on the recorded failure, and a judge given a deliberately
persuasive but wrong solver transcript still fails the artifact because it never sees it.

## M4 — Measurement: evals, ablation, calibration

**Goal:** compounding becomes measurable and self-deception gets structurally hard.

- Golden fixtures per task class with deterministic setup/teardown, and the **eval firewall**
  blocking distillation on fixture runs.
- Harness pinning library snapshot and model version; results stored per snapshot.
- **Ablation arm:** stratified control sampling at the governed rate, `causal_lift` with Wilson
  intervals, `fandea lift`.
- Calibration scoring of `predicted_success`; abstention precision.
- Per-task-class control baselines persisted, since per-skill contribution in M5 is measured
  against them.
- All metrics from specs §11 and specs §23, including `merge_gap_rate`, `parallel_speedup`,
  `fake_edge_rate`, and `judge_isolation_violations`; regression gate wired into promotion.

**Done when (engineering, per refactor-plan B7 — the harness measures correctly, it does not
require the product hypothesis to be true):** the harness correctly computes `causal_lift` and
its Wilson interval on a synthetic scenario with a known, injected lift, and correctly reports
"not established" on a synthetic scenario with a known, injected null effect; an intentionally
bad skill version is blocked by the regression gate; per-task-class control baselines persist
across snapshots. Whether real `repo-chore` traffic shows a positive `causal_lift` with an
interval excluding zero is a **research outcome**, tracked in
[`assumptions.md`](assumptions.md#a1), not a merge gate — a harness that correctly reports "not
established" on real traffic still passes M4.

## M5 — Earned autonomy, capacity, and retirement

**Goal:** relax the human gate exactly where evidence supports it, and give the library a floor.

- Shadow execution with offline comparison; shadow results never reach the caller.
- Trust scoring, decay, and lift reported together.
- Auto-promotion on the shadow thresholds; quarantine on consecutive field failures.
- **Bounded active set** per task class with `benched` as a reversible state, incumbent-displacement
  grace periods, and `active_cap_pressure` tracking.
- **Contribution estimates** against the M4 control baselines, with Wilson intervals.
- **Retirement** on `estimate <= -retirement_threshold` past `evidence_floor`, ledger-recorded, with
  parents of a benched child marked `needs_recert`.
- Curation prior in ranking; higher evidence bar for `self_distilled` promotion.

**Done when (engineering, per refactor-plan B7):** a skill reaches `approved` through shadow
evidence alone with no human decision; an injected regression drives a skill to `quarantined`
automatically; a skill with high trust but zero lift is *not* auto-promoted; a skill with
sustained negative contribution is benched and restorable; a skill below the evidence floor is
never benched on contribution; and a synthetic harsh configuration (evidence floor 20, threshold
0) is demonstrated, **on a synthetic environment with a known injected over-pruning effect**, to
underperform the loose defaults — this proves the mechanism can detect the failure mode
ADR-0006 exists to prevent. Whether this specific finding
([`references.md`](references.md) §1.2) replicates on our own golden sets and traffic volume is
a research outcome, tracked in [`assumptions.md`](assumptions.md#a2), not a merge gate: our
evidence floor default (30) is lower than the literature's (100) specifically because our
throughput is thinner (§A2), and confirming or revising it is ongoing, not a one-time M5 gate.

## M6 — Fan-out: portfolio and decomposition

**Goal:** convert model uncertainty into compute spend where validators can adjudicate, and run
genuinely independent work at once.

- `fan_out` / `join` in the engine with divided budgets and disjoint workspace clones.
- **Portfolio branches:** competing strategies, selection by required-criteria pass count, then
  advisory score, then cost. Losing branches written to episodic memory as compared alternatives.
- **Decomposition branches:** disjoint parts of the work, all-must-complete join, then synthesis.
  `plan` may only decompose when the locked criteria partition cleanly across branches, with
  whole-artifact criteria retained at the join.
- **Merge audits** recording expected against received; a gap files a `merge` verdict that
  re-dispatches only the missing branches once, rather than retrying the branches that succeeded.
- **Layered fan-in** above the layer threshold, with deterministic code reduction where the
  combination is mechanical.
- Resource-claim disjointness enforced across branches; uncompensable `external` effects blocked
  from portfolio and shadow modes.

**Done when:** portfolio runs beat single-strategy runs on first-attempt success for ambiguous
tasks at bounded cost; decomposition runs finish at the speed of the slowest part rather than the
sum; total spend never exceeds the parent budget; a tie is broken by cost, not by model
preference; a killed branch causes a visible merge failure rather than a plausible-looking
partial result; `merge_gap_rate` is zero across the golden sets, without which the speedup number
means nothing; and a decomposition whose criteria cannot be partitioned is refused at `plan`
rather than split anyway.

## M7 — Improvement plane

**Goal:** the system reorganises, practises, and re-certifies without a user waiting.

- Job runner with per-job budgets; proposals-only write path.
- **Miner:** bootstrap candidates from git history, merged PRs, CI config, runbooks, marked
  `mined_from_human_artifact`. Treated as a primary quality source, not just cold-start relief.
- **Curator:** active-set recomputation and retirement first, then extract-child, split,
  tighten-precondition, merge, compact. Deduplication is last because a consistent authoring prior
  largely subsumes it ([`references.md`](references.md) §1.2).
- **Step-graph proposals:** `parallelise` removes edges that failed the fake-edge test across ≥5
  runs; `serialise` adds edges or widens claims after repeated merge failures or conflicts. Both
  are ordinary versioned diffs behind the golden-set gate, which is what makes concurrency a
  learned property of a skill rather than a guess the distiller made once.
- **Practice:** curriculum targeting `predicted_success ∈ [0.2, 0.8]`, fed by one-off clusters
  and failure-heavy classes; excluded from user-facing metrics.
- **Recertifier:** scheduled and triggered re-validation, re-running sensitivity proofs.
- **Correction miner:** cluster reviewer edits into T2 proposals.

**Done when:** the Miner produces validated approved skills on a repository with no prior runs;
Curator proposals reduce library size while `retrieval_precision_at_3` holds or improves;
Practice converts one-off clusters into approved skills; a tool upgrade drives affected skills to
`needs_recert` automatically; a skill whose steps were serialised for no reason is parallelised by
proposal and shows measurable `parallel_speedup` with no golden-set regression; no job can write
`approved` state directly.

## M8 — Composite skills

**Goal:** coverage grows faster than library size.

- `uses` resolution with pinned children, cycle rejection, depth bound.
- Transitive invalidation: child quarantine sets pinning parents to `needs_recert`.
- Curator-proposed child extraction with parent rewrites as reviewable diffs.
- Budget and attribution accounting across composition depth.

**Done when:** at least one parent skill composes children in production, `mean_composition_depth`
rises while library size grows sublinearly with solved task variety, and quarantining a child
provably blocks its parents from being retrieved as `approved`.

## M9 — Second domain, governance, hardening

**Goal:** prove the architecture is not domain-specific, then make it operable.

- Add a second task class (e.g. research → structured synthesis) with **no structural change**
  to graph, schemas, or services. Any change required here is a design defect to fix.
- Full policy-proposal flow: T2 changes proposed, eval-compared, human-approved, ledger-recorded.
- Container-isolated sandbox; approval gates for all non-`read` tools.
- Postgres + `pgvector`; migration exercised on a real snapshot.
- Scope model and cross-scope promotion with redaction.
- OpenTelemetry spans and all required events; operational dashboards.
- Concurrency: write serialisation on version allocation, read-your-writes per run.

**Done when:** the second domain runs on the unchanged runtime with no structural change to
graph, schema, or services — this is engineering-checkable and the actual point of M9. Whether
it also reaches positive reuse rate and lift is, per B7, a research outcome to report, not a
condition of M9 being done; a domain that runs correctly and honestly reports "not established"
still passes. A T2 change cannot land without a recorded approver and eval comparison;
concurrent runs produce no duplicate or missing versions under load.

## Graph-execution work in sequence

The four graph-execution mechanisms — step dependency graphs, resource claims, verifier
isolation, and merge completeness — cut across milestones rather than forming one of their own.
Collected here so the ordering is legible in one place, with what proves each piece and what
happens if it goes wrong.

| Mechanism | Lands in | Depends on | Proof it works | If it misbehaves |
| --- | --- | --- | --- | --- |
| `merge` failure class and wave-level rollback | M0 | Nothing; it is part of the taxonomy and the snapshot model | A run with a killed unit is classified `merge`, not `execution`, and restores whole | Class is inert until fan-out exists; no rollback needed |
| Resource claims in the tool registry | M2 | Tool registry | Two steps claiming the same `write` id serialise; a claim timeout re-runs the wave serially | Widen every claim to `exclusive`, which costs latency and nothing else |
| Step DAG execution and wave recording | M2 | Claims, snapshots | Independent steps overlap; `step_waves` reconstructs the attempt in replay | Set `max_parallel_steps = 1`; the DAG degenerates to the list it replaced |
| Contention aggregation into the affordance plane | M2 | Claims, affordance plane | An observed ceiling of one on a rate-limited service suppresses parallel dispatch | Aggregates are derived (T0) and rebuildable; drop them |
| Verifier isolation and lenses | M3 | Validation runner, criteria locking | A judge fed a persuasive-but-wrong transcript still fails the artifact, because it never receives one | No fallback: judges are advisory, so the safe failure is to stop scoring them |
| Concurrency and merge metrics | M4 | Harness | `parallel_speedup` reported beside `merge_gap_rate`, never alone | Metrics only; report as "not established" |
| Fan-out kinds, merge audits, layered fan-in | M6 | Engine fan-out, `merge` class | Decomposition finishes at the slowest part, and a gap fails visibly | Disable decomposition and keep portfolio; the audit stays |
| `parallelise` and `serialise` proposals | M7 | Run history, golden-set gate | A wrongly serial skill is parallelised by proposal with no regression | Proposals are versioned diffs; revert the version |

Three ordering constraints are worth stating, because getting them backwards is expensive:

1. **Claims before concurrency.** Running steps concurrently before shared resources are declared
   produces corruption that presents as random tool failures, and the transcript will not say why.
   The registry work in M2 is therefore a precondition for the scheduler in the same milestone,
   not a parallel workstream.
2. **Audits with the first fan-in, not after it.** The audit ships in the same change as `join`
   in M6, which is why the `merge` class exists from M0 and sits unused until then. A join written
   to tolerate gaps and hardened later is a join that has already returned wrong answers nobody
   noticed.
3. **Isolation before autonomy.** Judges are isolated in M3, two milestones before earned autonomy
   in M5. A judge that agrees with the solver is a self-grading loop, and granting autonomy on top
   of one produces confident metrics with nothing behind them.

## Test strategy

| Layer | Approach |
| --- | --- |
| Unit | Nodes as pure `(state) -> (delta, route)` functions with fake services |
| Property | Hypothesis over the state machine: budgets never exceeded, no unbounded cycles, no retry on a dirty workspace, `results_history` monotonic |
| Contract | Every `skills/**/*.json` and `facts/**/*.json` validated in CI; placeholder binding and `uses` acyclicity checked |
| Boundary | Import-graph test proving run and job code cannot reach T3 modules |
| Replay | Recorded transcripts drive nodes deterministically, no live models |
| Regression | Golden sets per task class, gating promotion |
| Adversarial | Planted vacuous criteria, planted secrets, poisoned memory documents, injected instructions in tool output |
| Concurrency | Independent steps overlap in time; conflicting resource claims serialise; a wave rolls back whole; a claim timeout re-runs serially instead of hanging; killed branches surface as merge failures |
| E2E | Full loop on a scratch repo fixture, including checkpoint kill/resume and control-arm runs |

CI-asserted invariants: no write to an existing `SkillVersion`; every back-edge decrements a
budget; no `approved` skill has only `judge` criteria; every required criterion has a sensitivity
proof; every `loop` has `max_iterations`; the `uses` graph is acyclic with depth ≤ 3; eval
fixtures never appear in skill provenance; `ablation_rate` is unreachable from run and job code;
`active_cap` and `retirement_threshold` are finite and non-zero; no retirement occurs below the
evidence floor; every step's `depends_on` resolves within an acyclic graph; every `judge`
criterion is `fresh_context` and every judge result carries a context hash containing no
transcript content; no step wave contains two conflicting claims; every fan-in emits a merge
audit; and no synthesis executes on an audit with missing inputs. Per this refactor
([ADR-0009](adr/0009-contracts-as-code.md)): `schema/*.schema.json` has zero drift from
`contracts/` (`scripts/generate_schemas.py --check`); the canonical examples pass their
semantic profile, not merely parse; every node in the route table
(`contracts/graph.py`) has ≥1 legal outgoing route; every `FailureClass` has ≥1 producing
source; and `RunState.criteria` never type-checks a `SkillCertificationCriterion`.

## Risks and mitigations

| Risk | Why it bites | Mitigation |
| --- | --- | --- |
| Distilled skills are plausible but useless | Models write convincing steps that do not generalise | Reusability filter, `library_yield`, approval gate |
| Retrieval anchors the solver wrongly | A wrong skill is worse than none | Score floor, preconditions, `abstain`, `retrieval` failure class tightening preconditions |
| Criteria drift toward easiness | Weak criteria make everything pass and then certify future work | Pre-registration, sensitivity proofs, `criteria_weakened` review flag, no self-repair |
| Metrics improve while capability does not | The comfortable failure mode: nobody can tell | Ablation control arm, eval firewall, manifests, calibration |
| Trust without causation | A skill applied to easy tasks looks excellent | Lift reported with trust; no auto-promotion on trust alone |
| Library entropy | Retrieval precision decays as size grows | Curator compaction and abstraction, `retrieval_decay` early warning |
| Library drift | Unbounded growth erodes quality with no performance floor | Bounded active cap plus contribution-score retirement (specs §24) |
| Over-pruning | Aggressive retirement measured worse than no library | Evidence floor, loose threshold, reversible benching, `retirement_reversal_rate` |
| Self-distilled skills may add nothing | Measured +0.0pp in one benchmark against +16.2pp human-curated | `curation_gap` metric to test it in our domain; Miner as a primary source; higher bar for `self_distilled` |
| Skill rot | Tools and models change underneath | Environment fingerprints, model-version gates, scheduled recertification, trust decay |
| Memory poisoning or injection | Model-authored memory re-enters context | Memory-as-data discipline, hash-chained ledger, provenance-weighted trust, adversarial tests |
| Practice burns budget on noise | Curriculum drifts to trivial or impossible tasks | Target the 0.2–0.8 band, separate budget, `practice_conversion` metric |
| Composition brittleness | Deep chains break opaquely | Pinned children, depth ≤ 3, transitive invalidation, parent-level criteria |
| Hidden edges | Steps share a file, lock, or rate-limited API without declaring it | Resource claims in the tool registry; conflicting claims serialise; concurrency tests |
| Silent partial results | A dead branch disappears into a synthesis that looks complete | Merge audits with expected-versus-received; decomposition joins fail on gaps |
| Judges that agree instead of check | A verifier inheriting the worker's context grades its own reasoning | Fresh-context judges, distinct lenses, isolation mode recorded per result |
| Cost blowup | Loops and fan-out multiply spend | Per-run cost budget, divided branch budgets, escalation ladder |
| Unsafe self-modification | Optimising the objective by weakening constraints | T0–T3 tiering with import-boundary enforcement |
| Engine scope creep | In-house engine becomes a framework | ADR-0001 revisit trigger |

## Immediate next actions

M0–M9 engineering done-whens are implemented and covered by the test suite. Remaining work is
operational hardening called out under M9 (container sandbox, Postgres/`pgvector`, scope model,
OpenTelemetry dashboards) and ongoing research outcomes tracked in
[`assumptions.md`](assumptions.md) — not further milestone scaffolding.
