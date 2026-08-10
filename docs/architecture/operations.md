# Recertia Architecture: 9. Storage choices

## 9. Storage choices

| Concern | v1 | Upgrade path | Why |
| --- | --- | --- | --- |
| `SkillVersion`, facts, policy | JSON in git | Same, plus signed tags | Diffable, reviewable, revertible — this is the immutable half of ADR-0007's split |
| `SkillStatus`, `SkillStats`, cases | SQLite | Postgres | Runtime state, not reviewed artifacts — append-only event log and derived rows (ADR-0007), zero-ops start, identical SQL surface |
| Vector index (per plane) | `sqlite-vec` | `pgvector` | Co-located with metadata |
| Lexical index | SQLite FTS5 | Postgres `tsvector` | Same |
| Transcripts, snapshots | Content-addressed blobs on disk | Object storage | Large, write-once, dedupable |
| Checkpoints | SQLite rows | Postgres | Must survive process death |
| Integrity ledger | Append-only hash-chained table | Same, externally anchored | Tamper-evident provenance (§15.1) |

The v1 column lets one developer run everything locally with no services; the upgrade path is
a driver swap rather than a data model change.

## 10. Bounded loops and attempt isolation

### 10.1 Budgets

| Budget | Enforced at | Default |
| --- | --- | --- |
| `max_attempts` | `evolve → solve` | 4 |
| `max_tool_calls` | tool runtime | 200 |
| `max_tokens` | solver | task class default |
| `max_wall_clock_s` | solver, per attempt | 900 |
| `max_cost_usd` | solver + tool runtime | task class default |
| `max_branches` | `fan_out` | 3 |
| `max_parallel_steps` | step scheduler in `solve` | 8 |
| `claim_timeout_s` | resource claim acquisition | 60 |
| `max_versions_written` | `store` | 2 |

Exhausting any budget routes to `classify_failure` then `record_dead_end`, never to another
`solve`. No-progress detection short-circuits when two consecutive attempts produce an
identical result vector: the same failure twice means the current strategy is exhausted, not
unlucky.

A budget is only as good as the meter behind it, so `RunState.spent` has exactly one writer:
`AttemptMeter` in `recertia.nodes.attempt`. Each `solve` path opens a meter, charges what it
uses, and closes through the meter's outcome helpers, which means no exit can record an
attempt while omitting a dimension — the failure mode that left wall clock uncharged and
therefore unenforceable.

Charging is per attempt, while the model client, tool runtime, and claim scheduler count
cumulatively for the whole run. `RuntimeWindow` reports the difference between two reads of
those counters; reading them directly charges an attempt for every attempt before it. The
window is measured inside `ctx.op_once` and persisted alongside the operation result, so a
resumed run charges replayed work exactly once rather than losing it. A boundary test parses
the AST to keep both rules enforced rather than merely documented.

Budgets are also *allocated*, not just capped. The policy plane holds an escalation ladder —
start on a cheap model tier, escalate on specific failure classes — because spending
frontier-model budget on a task that a cheap tier solves is the most common way cost per
solved task fails to improve even as success rates do.

### 10.2 Attempt isolation and compensation

`solve` mutates a workspace, so retrying naively means attempt 2 starts from attempt 1's
mess — a bug that produces uninterpretable failures and poisons distillation. Therefore:

- Each attempt runs against a workspace snapshot taken before it starts.
- `evolve` restores the snapshot before routing back to `solve`, so every attempt starts
  from a known state, and the diff between attempts is attributable.
- Fan-out branches get disjoint workspace clones.
- Steps running in the same wave share the attempt's workspace, so the wave — not the step —
  is the unit of rollback. Restoring half a wave would leave a state no attempt ever produced.
- Irreversible external side effects (`external` tools) are gated by approval and recorded
  with a compensating action where one exists; a skill whose steps include an uncompensable
  external effect cannot run in `portfolio` or `shadow` mode.
