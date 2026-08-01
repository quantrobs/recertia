# Fandea Architecture: 16. Measuring compounding

## 16. Measuring compounding

Tracked per task class over library snapshots:

| Metric | Why it is here |
| --- | --- |
| `reuse_rate` | Is memory being used at all |
| `first_attempt_success` | The headline: retrieval should raise it |
| `causal_lift` | Treatment minus control from the ablation arm — the only causal number |
| `attempts_to_success` | Should fall |
| `cost_per_solved_task` | Should fall; catches "success bought with frontier-model spend" |
| `regression_rate` | Catches "evolution" that is really damage |
| `retrieval_precision_at_3` | The thesis rests on retrieval being right |
| `library_yield` | Anti-vanity: approved skills nobody reuses drive it down |
| `calibration_error` | Brier score of `predicted_success`; does the system know what it can do |
| `abstention_precision` | Were abstentions actually the unsolvable ones |
| `recert_pass_rate` | Is the library rotting |
| `mean_composition_depth` | Is abstraction happening, or is the library just growing |
| `skill_contribution` | Per-skill shadow−suppression lift; the retirement input (§7.2) |
| `active_cap_pressure` | Share of task classes at their cap; high pressure means value is being benched by competition |
| `retirement_reversal_rate` | Benched skills later restored; a high rate means retirement is too aggressive |
| `curation_gap` | First-attempt success of human-authored and mined skills minus self-distilled ones; tests the SkillsBench finding in our domain |
| `merge_gap_rate` | Fan-ins that lost an input; the number that says whether parallelism is honest |
| `parallel_speedup` | Serial step time over observed wall clock, per skill; the only justification for step graphs |
| `fake_edge_rate` | Declared bindings whose bound inputs go unused at runtime; leftover serialisation after store-time edges are data-carrying |
| `judge_isolation_violations` | Judge invocations that saw solver reasoning; a release blocker at any value above zero |

A library change that raises size without moving `first_attempt_success`, `causal_lift`, or
cost is not an improvement, and the harness makes that visible. The same discipline applies
to the concurrency metrics: `parallel_speedup` is only reportable next to `merge_gap_rate`,
because a graph that finishes faster by dropping a branch will show excellent speedup.

## 17. Domain scoping for v1

Prove the loop on one narrow domain before opening discovery, because a narrow domain is
where success criteria are genuinely machine-checkable. Recommended first domain:
**repository chores** — dependency bumps, lint and type fixes, test scaffolding, release
notes. Success is defined by existing tooling, tasks recur with real variation, artifacts are
diffs, and there is a rich history for the Miner to bootstrap from.

Then add a second domain and require that the graph, schemas, and services take **no**
structural change to absorb it. Anything that must change is a design defect to fix, not to
work around.

## 18. Deliberately deferred

Recorded so their absence is a decision rather than an oversight:

| Deferred | Why |
| --- | --- |
| Fine-tuning on mined corrections | Correction data must be plentiful and clean first; representational learning has more headroom now |
| Learned retrieval ranker | Needs labelled applicability data that the ablation arm and review queue will produce |
| RL over the policy plane | Reward hacking risk is unacceptable before the ablation arm and sensitivity proofs are trusted |
| Cross-tenant or federated learning | Requires the scope and redaction model to be proven single-tenant first |
| Multi-agent negotiation beyond portfolio fan-out | Portfolio plus critic separation captures most of the benefit at a fraction of the complexity |
| Self-authored tools | T3 boundary: a system that writes its own tools writes its own permissions |
