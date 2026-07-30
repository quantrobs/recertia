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

## Technology stack

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

```text
fandea/
├── pyproject.toml
├── schema/                    # JSON Schema contracts
├── skills/<skill_id>/v<N>.json     # procedural memory, canonical
├── facts/<scope>/<slug>.json       # semantic memory, canonical
├── policy/                          # T2 config, versioned and reviewed
├── src/fandea/
│   ├── graph/                 # engine: registry, router, checkpoints, budgets, fan-out
│   ├── nodes/                 # intake, retrieve, plan, fan_out, solve, validate, join,
│   │                          # classify_failure, evolve, distill, review, store,
│   │                          # quarantine, finalize
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

- Graph engine: node registry, typed `RunState`, conditional edges, per-node checkpoints,
  budget accounting enforced on back-edges.
- All fourteen nodes stubbed; `solve` is a scripted tool sequence.
- `validate` runs `command` criteria for real in the subprocess sandbox.
- **Criteria locking** at `intake` with hash recorded in the run manifest.
- **Attempt isolation:** workspace snapshot before each attempt, restore in `evolve`.
- **Failure classification** with the seven-class taxonomy, driving `evolve` move selection.
- **Ledger:** append-only hash chain with `verify`.
- **Governance skeleton:** tier registry plus a CI import-boundary test proving `nodes/` and
  `jobs/` cannot import `governance/` or `evals/ablation`.
- CLI `fandea run`, `fandea runs show --route-log`, `fandea ledger verify`.

**Done when:** a run reaches `finalize` with `terminal="solved"`; killing the process mid-run
and resuming completes it from the last checkpoint; a run whose criteria always fail terminates
at `quarantine` with a failure class rather than looping; retrying always starts from a clean
snapshot; the boundary test fails if a node imports a T3 module.

## M1 — Procedural memory and retrieval

**Goal:** hand-authored skills are found and applied. No distillation yet.

- `skill.schema.json` enforcement, including placeholder binding and `uses` validation.
- Skill store with immutability guard (any write to an existing version is refused), lineage,
  and git adapter.
- Index build from canonical files with snapshot ids; embeddings + FTS5.
- Retrieval pipeline: generation, RRF merge, precondition filter including environment
  fingerprint, rerank, score floor, staleness decay.
- `plan` chooses `apply` / `adapt` / `scratch` / `abstain` with `predicted_success`.
- 8–12 hand-authored `repo-chore` skills.
- `fandea skills lint`, `fandea skills search --explain`.

**Done when:** `retrieval_precision_at_3` ≥ 0.7 on a labelled probe set; unrelated tasks return
an empty bundle; novel tasks route to `scratch`; a skill whose environment fingerprint does not
match is dropped rather than down-ranked.

## M2 — Solver, tool runtime, episodic and affordance memory

**Goal:** real model-driven solving that produces distillable transcripts and remembers failures.

- Model client with retry, timeout, token and cost accounting.
- Tool registry with side-effect classes and approval hooks; tools for the first domain.
- Structured transcript writer, content-addressed.
- Skill application: parameter binding, step execution, `steps[].loop` bounds.
- **Episodic writes for every attempt**, including `dead_end` records with reasons.
- **Affordance telemetry:** durations, error signatures, flake rates.
- `evolve` implements all repair moves from specs §16, consults dead ends to avoid repeats, and
  short-circuits on identical result vectors.

**Done when:** golden `repo-chore` tasks are solved end-to-end via applied skills; a task that
previously failed a given way does not repeat that approach; a known-flaky tool produces a
`tool` classification that leaves skill trust untouched; replay tests reconstruct node decisions
with no model calls.

## M3 — Distillation, facts, review

**Goal:** the loop closes. Successful runs produce reviewed memory.

- Critic pass proposing criteria pre-solve when the caller supplies none.
- **Sensitivity proofs** generated and stored per criterion; unproven criteria are advisory.
- Distiller: parameter extraction, generalisation, pruning, criteria proposal, **fact
  extraction**.
- Reusability filter, `one_off` recording per task class, near-duplicate routing to a new
  version of the nearest skill.
- Fact store with verification, confidence, and contradiction retention.
- Hygiene scan at store time; failing drafts rejected.
- Review service, queue, decisions; `store` writes transactionally and appends to the ledger.

**Done when:** a novel task solved from scratch yields a `candidate` skill a reviewer approves,
and a later similar task retrieves and applies it with `attempt_no == 1`. That transition is the
system's core claim. Also: a deliberately vacuous criterion is rejected by its sensitivity
check, and a draft containing a planted secret is refused.

## M4 — Measurement: evals, ablation, calibration

**Goal:** compounding becomes measurable and self-deception gets structurally hard.

- Golden fixtures per task class with deterministic setup/teardown, and the **eval firewall**
  blocking distillation on fixture runs.
- Harness pinning library snapshot and model version; results stored per snapshot.
- **Ablation arm:** stratified control sampling at the governed rate, `causal_lift` with Wilson
  intervals, `fandea lift`.
- Calibration scoring of `predicted_success`; abstention precision.
- All metrics from specs §11 and §23; regression gate wired into promotion.

**Done when:** the harness shows first-attempt success and cost per solved task improving
against an empty-memory baseline; `causal_lift` is positive with an interval excluding zero; an
intentionally bad skill version is blocked by the regression gate; a lift claim with an interval
spanning zero is reported as "not established".

## M5 — Earned autonomy

**Goal:** relax the human gate exactly where evidence supports it.

- Shadow execution with offline comparison; shadow results never reach the caller.
- Trust scoring, decay, and lift reported together.
- Auto-promotion on the shadow thresholds; quarantine on consecutive field failures.

**Done when:** a skill reaches `approved` through shadow evidence alone with no human decision,
an injected regression drives a skill to `quarantined` automatically, and a skill with high
trust but zero lift is *not* auto-promoted.

## M6 — Portfolio fan-out

**Goal:** convert model uncertainty into compute spend where validators can adjudicate.

- `fan_out` / `join` in the engine with divided budgets and disjoint workspace clones.
- Selection by required-criteria pass count, then advisory score, then cost.
- Losing branches written to episodic memory as compared alternatives.
- Uncompensable `external` effects blocked from portfolio and shadow modes.

**Done when:** portfolio runs beat single-strategy runs on first-attempt success for ambiguous
tasks at bounded cost; total spend never exceeds the parent budget; a tie is broken by cost, not
by model preference.

## M7 — Improvement plane

**Goal:** the system reorganises, practises, and re-certifies without a user waiting.

- Job runner with per-job budgets; proposals-only write path.
- **Miner:** bootstrap candidates from git history, merged PRs, CI config, runbooks.
- **Curator:** merge, extract-child, split, deprecate, tighten-precondition, compact.
- **Practice:** curriculum targeting `predicted_success ∈ [0.2, 0.8]`, fed by one-off clusters
  and failure-heavy classes; excluded from user-facing metrics.
- **Recertifier:** scheduled and triggered re-validation, re-running sensitivity proofs.
- **Correction miner:** cluster reviewer edits into T2 proposals.

**Done when:** the Miner produces validated approved skills on a repository with no prior runs;
Curator proposals reduce library size while `retrieval_precision_at_3` holds or improves;
Practice converts one-off clusters into approved skills; a tool upgrade drives affected skills to
`needs_recert` automatically; no job can write `approved` state directly.

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

**Done when:** the second domain reaches positive reuse rate and lift on the unchanged runtime;
a T2 change cannot land without a recorded approver and eval comparison; concurrent runs produce
no duplicate or missing versions under load.

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
| E2E | Full loop on a scratch repo fixture, including checkpoint kill/resume and control-arm runs |

CI-asserted invariants: no write to an existing `SkillVersion`; every back-edge decrements a
budget; no `approved` skill has only `judge` criteria; every required criterion has a sensitivity
proof; every `loop` has `max_iterations`; the `uses` graph is acyclic with depth ≤ 3; eval
fixtures never appear in skill provenance; `ablation_rate` is unreachable from run and job code.

## Risks and mitigations

| Risk | Why it bites | Mitigation |
| --- | --- | --- |
| Distilled skills are plausible but useless | Models write convincing steps that do not generalise | Reusability filter, `library_yield`, approval gate |
| Retrieval anchors the solver wrongly | A wrong skill is worse than none | Score floor, preconditions, `abstain`, `retrieval` failure class tightening preconditions |
| Criteria drift toward easiness | Weak criteria make everything pass and then certify future work | Pre-registration, sensitivity proofs, `criteria_weakened` review flag, no self-repair |
| Metrics improve while capability does not | The comfortable failure mode: nobody can tell | Ablation control arm, eval firewall, manifests, calibration |
| Trust without causation | A skill applied to easy tasks looks excellent | Lift reported with trust; no auto-promotion on trust alone |
| Library entropy | Retrieval precision decays as size grows | Curator compaction and abstraction, `retrieval_decay` early warning |
| Skill rot | Tools and models change underneath | Environment fingerprints, model-version gates, scheduled recertification, trust decay |
| Memory poisoning or injection | Model-authored memory re-enters context | Memory-as-data discipline, hash-chained ledger, provenance-weighted trust, adversarial tests |
| Practice burns budget on noise | Curriculum drifts to trivial or impossible tasks | Target the 0.2–0.8 band, separate budget, `practice_conversion` metric |
| Composition brittleness | Deep chains break opaquely | Pinned children, depth ≤ 3, transitive invalidation, parent-level criteria |
| Cost blowup | Loops and fan-out multiply spend | Per-run cost budget, divided branch budgets, escalation ladder |
| Unsafe self-modification | Optimising the objective by weakening constraints | T0–T3 tiering with import-boundary enforcement |
| Engine scope creep | In-house engine becomes a framework | ADR-0001 revisit trigger |

## Immediate next actions

1. Scaffold `pyproject.toml`, `ruff`/`mypy` config, and CI running lint, types, schema contract
   tests, and the import-boundary test.
2. Implement the graph engine and `RunState` from specs §3, with checkpointing and budgets.
3. Stub all nodes with the routing predicates from specs §4.1, criteria locking at `intake`, and
   failure classification.
4. Implement workspace snapshot/restore, since correct retries are a precondition for every
   later measurement.
5. Land the first golden `repo-chore` fixture so M0's done-when is machine-checked.
