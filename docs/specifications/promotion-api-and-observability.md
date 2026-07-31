# Fandea Specifications: 8. Promotion policy

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

These are all `SkillStatus` transitions (§2.2, §2.5), made by the Curator or Recertifier reading
across runs — never by a single run's task-plane graph (§4, ADR-0008).

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
