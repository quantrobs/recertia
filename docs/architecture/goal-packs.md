# Recertia Architecture: Goal packs

Rationale and component design for migration programs. Normative rules:
[`../specifications/goal-packs.md`](../specifications/goal-packs.md). Decision:
[ADR-0014](../adr/0014-goal-packs-as-migration-programs.md).

## 1. Why packs exist

Recertia’s strength is **pre-registered, locked success criteria** per run. That strength
becomes a liability if operators stuff a multi-week refactor into one Goal: the lock cannot
honestly describe “characterize, then move, then delete” as one immutable predicate set.

At ~20k LOC, real migrations are **stacked changes** with:

- characterization before mutation,
- freeze zones (don’t touch API while flipping solver internals),
- seam-specific proofs (not only `pytest -q`),
- human review between landings.

A Goal pack is the control-plane object for that program. The data plane (graph, intake,
attempt isolation) stays per-run.

```text
                    ┌─────────────────────────────────────┐
   brief / probe    │  Compose propose (draft only)       │
         │          │  decompositions[] + stress          │
         ▼          └──────────────┬──────────────────────┘
   human accept                    │
         ▼                         ▼
   GoalPack (durable) ──── steps[] (Goals + freeze/deps)
         │
         │  per ready step, human confirm
         ▼
   materialize Goal (+ program_bar) → POST /v1/runs
         │
         ▼
   GraphOrchestrator (unchanged) → criteria_locked → solve/validate
         │
         ▼
   bind run_id on step → unlock dependents / handoff artifact
```

## 2. Relationship to existing concepts

| Concept | Pack relationship |
| --- | --- |
| `Goal` / `compile_goal` | Each step **is** a Goal when submitted |
| ADR-0003 lock | Unchanged; per run |
| `strategy_hint=decomposition` | Intra-run branching; packs are **inter-run** |
| Fan-out / branches | Attempt-scoped; not a migration program |
| Console templates | Small chores stay templates; packs cover multi-step migrations |
| Skills / promotion | Ordinary runs may distill; pack status ≠ approval |
| Replay packs | Different object (proposal evidence); do not confuse names in UX copy |

## 3. Storage

v1 (aligned with operations §9):

| Entity | Store |
| --- | --- |
| Pack + steps | JSON or SQLite under `{runs_root}/packs/<tenant_id>/` (same durability class as proposals) |
| Run binding | `step.run_id` → existing run records |
| Handoff artifacts (GP1) | Content-addressed snapshot / tar under blobs; referenced by `base_run_id` |
| Git tips (GP2) | Digest + ref recorded on step; checkout into fresh workspace |

Pack records are **not** reviewed git artifacts (unlike `SkillVersion`). They are operator
runtime state. Export-to-git (ADR note / PR series) is a later convenience, not the source
of truth for execution.

## 4. Materialization & bind

`materialize_step_goal` merges program bar (append-by-id; collisions with different bodies
fail). With `freeze_enforcement=hard`, freeze_paths become `must_not_modify`; under
**advisory** (GP0 default) they do not.

Preview returns `compile_goal` output + `budget_from_goal_constraints`. Execution path:

1. Preview / `plan_only` envelope from `POST …/steps/{id}/run`
2. Client `POST /v1/runs` with materialized Goal (+ workdir)
3. `bind_run_id` on the step (idempotent; appends `run_ids`, sets `current_run_id`)
4. Terminal mapping via `acceptance_gate`; failed step blocks the program

Materialize MUST be pure for criteria content given the same step revision (environment
fingerprint for proofs still applies at intake).

Types: `contracts/program.py`. Store: `{root}/programs.sqlite`.

## 5. Workspace continuity (the hard part)

Attempt isolation (ops §10.2) assumes a run owns a workspace and snapshots **within** that
run. Programs need continuity **between** runs without breaking that model.

**Chosen progression (revised after review):**

1. **`none` + external handoff / operator workdir (GP0)** — Durable board and locked
   per-step contracts. Continuity is the operator’s git branch/PR (`external_handoff`) or an
   explicit `workdir`. `plan_only` supports board/preview without pretending an empty
   workspace is a migration. Default `freeze_enforcement=advisory`.
2. **`freeze_enforcement=hard` (GP1)** — Only when `must_not_modify` is snapshot/digest-honest.
3. **`git_tip` or allowlisted `copy_forward` (GP2)** — Prefer git tip. Whole-tree copy-forward
   is a last resort with path allowlists and size caps. **No shared live mount. No
   auto-advance** in this phase.

**Rejected:** advertising hard freezes before criterion honesty; empty-workspace step runs
as the default migration path; DAG complexity in GP0.

## 6. Drafting quality (Compose)

Heuristic packs that always emit “Inventory / Structural / Behaviour + pytest” are a
**bootstrap**, not the product. Architecture target:

| Signal | Use |
| --- | --- |
| Intent keywords | Trigger pack vs single Goal |
| Optional probe | Path existence, test layout, import roots (read-only) |
| Decomposition library | Small set of opinionated shapes (`by_risk`, `by_layer`, `by_seam`) with slot fillers |
| Model | Fill seam-specific commands/paths into slots; never sole authority |

Multiple **decompositions** are first-class in the propose response so operators choose a
migration *shape*, not a paraphrase of context.

## 7. Failure and retries

- Failed step → pack `blocked`; dependents stay `planned`.
- Retry = new run bound to same step (prior `run_id` retained in history list) or clone step
  (implementation choice; MUST keep audit of attempts).
- Skip is explicit, noted, and non-evidential for mutate safety.
- Auto-advance (GP2) only after `succeeded` and policy flag; never on judge-only Goals.

## 8. Security and tenancy

- Same workdir rejection rules as `POST /v1/runs`.
- Pack IDs unguessable or authorized via tenant ACL.
- Probe and copy-forward MUST NOT read outside tenant roots / registered bindings.
- Multi-tenant GA still gated by production-readiness; packs inherit C5 isolation tests.

## 9. Observability

Emit structured events (JSONL / SSE compatible with console C2):

- `pack.accepted`, `pack.blocked`, `pack.completed`, `pack.abandoned`
- `pack.step.ready`, `pack.step.run_bound`, `pack.step.terminal`
- Include `pack_id`, `step_id`, `run_id`, `criteria_hash` (when locked)

Metrics: steps succeeded / blocked per pack; cost rollup vs pack budget; rate of
`generic_pytest_only` warnings (draft quality signal).

## 10. What we deliberately do not build first

- Automatic repo-wide architecture understanding as a prerequisite to packs.
- In-browser multi-file IDE for the whole migration.
- Merging pack steps into one graph execution with mutable criteria.
- Renaming “replay pack” — keep distinct copy (“Goal pack” vs “ReplayPack”).
