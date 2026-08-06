# Recertia Implementation Plan

Build order for the system in the [architecture overview](architecture/overview.md) against the
contracts in [core entities and skill contracts](specifications/core-entities.md). Milestones are
sequenced by dependency and by what
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
| Language | Python ≥3.11 | Matches `requires-python` in `pyproject.toml` |
| Packaging | `uv` + `pyproject.toml` | Fast, lockfile-based |
| Contracts | Pydantic v2 | Runtime validation of graph state and memory documents |
| API | FastAPI + Uvicorn | Optional extra (`api`); matches Pydantic models |
| Persistence | SQLite (`sqlite-vec`, FTS5) → Postgres (`pgvector`) | Driver-swap upgrade path; Postgres via optional extra |
| Canonical memory | JSON in git: `skills/`, `facts/`, `policy/` | Review = pull request; rollback = revert |
| Workspaces | Git worktrees or overlay copies, content-addressed snapshots | Per-attempt isolation (specs §17) |
| Job scheduling | APScheduler in v1 → external scheduler | Improvement plane jobs (specs §20) |
| Sandbox | Subprocess with rlimits in v1; container isolation before multi-tenant | See architecture/container-sandbox.md |
| Observability | Structured logs + OTel JSONL export | Dashboard JSON for operator GA |

## Milestone map

```text
M0  Contracts + governance boundary + empty engine          SHIPPED
M1  Graph execution + isolation + resource claims           SHIPPED
M2  Criteria integrity + eval firewall + sensitivity         SHIPPED
M3  Distiller + authoring prior + fact store                SHIPPED
M4  Measurement harness + ablation arm + lift reporting     SHIPPED
M5  Library lifecycle + capacity + retirement + autonomy    SHIPPED
M6  Practice curriculum + second domain                     SHIPPED
M7  Composition + layered fan-in + trajectory               SHIPPED
M8  API + console foundations + go-live wiring              SHIPPED
M9  Operator GA hardening + soak path                       SHIPPED
```

## M0 — Contracts, governance boundary, empty engine

**Goal:** structural source of truth and T0–T3 boundary enforced before any runtime.

- Pydantic contracts for run, criteria, skill, graph, resources, profiles; generated schemas; zero-drift CI.
- Import-boundary tests for T0–T3 self-modification tiers (ADR-0005).
- Empty graph orchestrator skeleton; no model calls yet.
- Seed library lint path and criteria pre-registration hooks.

**Done when:** contracts generate schemas; import-boundary tests pass; a criteria hash is locked at intake; no runtime path can import T3 modules from T0/T1.

## M1 — Graph execution, isolation, resource claims

**Goal:** deterministic graph walk with attempt isolation and declared resource claims.

- Graph orchestrator executes nodes with snapshot/restore and differential sync.
- Resource-claim scheduling; conflicting claims serialise.
- Wave recording and merge audits.
- Retrieval filter pipeline (generation, RRF, precondition, active-set, rerank).
- 8–12 hand-authored `repo-chore` seed skills with hygiene scan and sensitivity proofs.

**Done when:** `retrieval_precision_at_3` ≥ 0.7 on a labelled probe set; unrelated tasks return an empty bundle; novel tasks route to `scratch`; fingerprint mismatch drops rather than down-ranks; every seed skill passed its golden task before `approved`.

## M2 — Solver, tool runtime, episodic and affordance memory

**Goal:** real model-driven solving that produces distillable transcripts and remembers failures.

- Model client with retry, timeout, token and cost accounting.
- Tool registry with side-effect classes, resource claims, approval hooks.
- Structured transcript writer; skill application with dependency-ordered steps and loops.
- Episodic and affordance memory writes from attempts.

**Done when:** a scratch solve produces a content-addressed transcript; cost is non-zero on real providers; resource conflicts serialise; episodic memory is queryable for similar failures.

## M3 — Distiller, authoring prior, fact store

**Goal:** novel solves yield candidate skills under an authoring prior; facts are verified.

- Distiller from transcripts → candidate skills with `curation: self_distilled`.
- Reusability filter, one-off recording, near-duplicate routing.
- Fact store with verification, confidence, contradiction retention.
- Hygiene scan at store time; review queue.

**Done when:** a novel task solved from scratch yields a `candidate` skill a reviewer can approve or reject; facts with contradictions are retained not overwritten; hygiene failures reject drafts.

## M4 — Measurement harness, ablation arm, lift reporting

**Goal:** causal lift and evidence-floor metrics under a locked harness.

- Golden fixtures per task class; snapshot pinning; control vs treatment arms.
- `causal_lift` with Wilson intervals; `curation_gap` by provenance class.
- Eval firewall and sensitivity proofs enforced.

**Done when:** a scheduled eval run produces `causal_lift` with intervals; the control arm is the no-skill / frozen-library baseline; assumptions `a1`/`a2` can be updated from real traffic data as research outcomes (not a merge gate; status remains under evaluation until evidence exists).

## M5 — Library lifecycle, capacity, retirement, autonomy

**Goal:** bounded active set, evidence-floor retirement, first governed autonomy.

- Active-set capacity cap; contribution-score retirement with reversible benching.
- Evidence floor before contribution retirement (Ratchet finding).
- Promotion path past golden gate only; no auto-promotion on score alone.

**Done when:** active set stays under the configured cap; retirement is reversible; a promotion packet requires golden-gate pass; `retirement_reversal_rate` is reported.

## M6 — Practice curriculum and second domain

**Goal:** practice loop on the 0.2–0.8 band; second domain fixtures for generality.

- Practice job targeting intermediate difficulty; separate budget; `practice_conversion` metric.
- `research-synthesis` golden fixtures as second domain.

**Done when:** practice job runs on a schedule; second-domain lift is reported alongside the first domain; practice does not consume the production budget.

## M7 — Composition, layered fan-in, trajectory

**Goal:** skill composition with pinned children; trajectory and counterfactual replay substrate.

- Composition depth ≤ 3; transitive invalidation; parent-level criteria.
- Trajectory store and replay packs (ADR-0011).
- Layered fan-in with merge audits.

**Done when:** a composite skill fails closed on missing children; replay packs attach to curator proposals; merge audits catch silent partial results.

## M8 — API, console foundations, go-live wiring

**Goal:** FastAPI surface, console read path, go-live operator path.

- `/v1` runs, skills, metrics; Pilot SPA read-only; structured API keys with scopes.
- Container sandbox defaults; path containment; id validation.

**Done when:** CLI and API produce fully pinned run manifests; container backend is the default; API keys enforce scopes and rate limits.

## M9 — Operator GA hardening and soak path

**Goal:** cost accounting, injection defenses, observe–act loop, soak/backup guidance.

- Pricing table and non-zero cost propagation; command policy on `agent_subtask`; observe–act scratch loop; manifest pinning on all operator paths; soak environment docs.

**Done when:** cost is non-zero through Spend on real providers; adversarial regression for prompt injection via fetch exists; CLI run manifests are fully populated; go-live.md documents RPO/backup and weekly soak cadence.

## Risk register (selected)

| Risk | Mitigation |
| --- | --- |
| Capacity floor | Bounded active cap plus contribution-score retirement (specs §24) |
| Over-pruning | Evidence floor, loose threshold, reversible benching |
| Self-distilled skills may add nothing | `curation_gap` metric; higher bar for `self_distilled` |
| Skill rot | Environment fingerprints, model-version gates, recertification |
| Memory poisoning | Memory-as-data, hash-chained ledger, provenance-weighted trust |
| Cost blowup | Per-run cost budget, divided branch budgets |
| Unsafe self-modification | T0–T3 tiering with import-boundary enforcement |

## Immediate next actions

M0–M9 and operational hardening are implemented. Remaining work is research outcomes in
[`assumptions.md`](assumptions.md) under real traffic, plus live-system soak (Docker/Postgres)
outside offline CI.
