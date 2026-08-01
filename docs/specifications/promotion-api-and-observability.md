# Recertia Specifications: 8. Promotion policy

## 8. Promotion policy

```text
draft      → candidate : all non-judge criteria passed during the originating run
candidate  → shadow    : task_class has an eval set with >= 5 golden tasks
shadow     → candidate : >= 10 shadow applications
                         AND lift / success thresholds (maybe_advance_shadow_to_candidate)
candidate  → approved  : golden-gated promote_to_approved (human approval is the v1 default path;
                         post-shadow eligibility still requires the same golden gate)
approved   → deprecated: a newer version of the same skill reaches approved
any        → quarantined: 2 consecutive field failures, or a reviewer rejection
```

These are all `SkillStatus` transitions (§2.2, §2.5), made by the Curator or Recertifier reading
across runs — never by a single run's task-plane graph (§4, ADR-0008). Shadow autonomy advances
only to `candidate`; it MUST NOT write `approved`.

Regression gate: before any promotion to `approved`, the golden set for the skill's
`task_class` MUST run green against the candidate via `promote_to_approved`. A regression blocks
promotion and is reported with the failing task ids.

## 9. HTTP API

Versioned under `/v1`. JSON only. Auth: `X-API-Key` with scoped keys (`runs`, `blobs`, `metrics`, `admin`).

### Implemented (offline)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `POST` | `/v1/runs` | Execute a task via `GraphOrchestrator.start` (sync, offline; same path as `recertia run`). Body: `request`, optional `task_class`, `criteria`, `script`, `budget`, `workdir`, `run_id`, `arm`. Returns terminal state + `route_log`. |
| `GET` | `/v1/runs/{run_id}` | Status / terminal / route log (memory + checkpoint fallback) |
| `POST` | `/v1/runs/{run_id}/resume` | Resume from last checkpoint |
| `POST` | `/v1/blobs` · `GET` `/v1/blobs/{digest}` | Content-addressed blob put/get |
| `GET` | `/v1/metrics/dashboard` | Telemetry dashboard panels |

`POST /v1/runs` is **not** enqueue-only: it drives the graph to a terminal (or error) before responding.

### CLI-only today (not yet HTTP)

`recertia skills search`, `recertia skills promote`, `recertia lift`, `recertia ledger verify` — use the CLI. Lift and skills search are intentionally not duplicated on HTTP yet.

### Aspirational (not implemented)

Console-oriented routes (list runs, async + SSE, proposals, jobs, promote enqueue, OIDC)
are specified normatively in [`product-console.md`](product-console.md) and sequenced as
milestones **C0–C5** in [`../implementation-plan-console.md`](../implementation-plan-console.md).
The table below remains the short index; **product-console.md wins on conflicts** for those
milestones.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/runs` | List/filter runs (console C0) |
| `GET` | `/v1/runs/{run_id}/transcript` | Structured transcript |
| `GET` | `/v1/runs/{run_id}/events` | SSE run event stream (console C2) |
| `POST` | `/v1/runs/{run_id}/cancel` | Cooperative cancel at next node boundary |
| `GET` | `/v1/skills` | List/filter by `task_class`, `lifecycle`, `tag` |
| `GET` | `/v1/skills/{skill_id}/versions/{version}` | Full skill version |
| `POST` | `/v1/skills/search` | Retrieval debug endpoint: scores and drop reasons |
| `POST` | `/v1/skills/…/promote` | Enqueue golden-gated promote (console C1) |
| `GET` | `/v1/reviews?status=pending` | Review queue |
| `POST` | `/v1/reviews/{decision_id}` | `approve` / `reject` / `request_changes` |
| `POST` | `/v1/evals/runs` | Run a golden set against a library snapshot |
| `GET` | `/v1/metrics` · `/v1/metrics/report` | Compounding metrics by task class and snapshot |
| `GET` | `/v1/facts` · `/v1/cases` · `/v1/affordances` | Read the non-procedural memory planes (§13) |
| `POST` | `/v1/memory/query` | Federated retrieval debug across all planes with drop reasons |
| `GET` | `/v1/jobs` · `POST` `/v1/jobs/{job}/run` | Improvement-plane job status and manual trigger (§20) |
| `GET` | `/v1/proposals?status=pending` | Curator, Miner and Correction-miner proposals awaiting review |
| `GET` | `/v1/policy` · `POST` `/v1/policy/proposals` | Read policy config; propose a T2 change, which requires human approval (§22) |
| `GET` | `/v1/ledger/verify` | Verify the integrity chain (§21) |

Error envelope (target shape; current handlers may return FastAPI `{detail: ...}`):

```json
{ "error": { "code": "budget_exhausted", "message": "...", "run_id": "01JD...", "retryable": false } }
```

## 10. CLI

### Implemented

```bash
recertia run --spec task.json [--runs-root .recertia] [--run-id ...] [--ablation]
recertia resume <run_id> [--runs-root .recertia] [--spec task.json]
recertia runs show <run_id> [--route-log]
recertia skills lint [--skills-root skills]
recertia skills search "dependency bump" --explain
recertia skills promote <skill_id> --version N --golden-dir PATH
# or: --golden-root PATH [--require-task-class-gate]
recertia ledger verify [--runs-root .recertia]
recertia lift --task-class repo-chore
recertia keys issue|revoke|list
```

### Aspirational (not implemented)

```bash
recertia skills list [--task-class repo-chore] [--lifecycle candidate]
recertia skills show bump-python-dep@3
recertia review queue
recertia review approve <decision_id> --note "..."
recertia eval run --task-class repo-chore --snapshot HEAD
recertia metrics --task-class repo-chore --compare HEAD~5..HEAD
recertia memory query "dependency bump" --planes skills,facts,cases --explain
recertia facts list --scope project
recertia cases show <case_id>
recertia jobs run curator --dry-run
recertia jobs run practice --task-class repo-chore --budget cost=5.00
recertia jobs run recertify --stale-days 30
recertia proposals queue
recertia policy show
recertia policy propose retrieval.min_score=0.60 --eval-compare
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
