# ADR-0015: Search and compression live on the improvement plane

- **Status:** accepted
- **Date:** 2026-08-12

## Context

SkillHEX, SkillProx, SkillAligner, Feedback Dynamics, PoisonedEvolution, and the 138K
packaging-lint study suggest useful mechanisms. An earlier plan put tree search and a new
`align_skills` node on the task graph. That fights [ADR-0004](0004-offline-improvement-plane.md),
[ADR-0005](0005-self-modification-boundary.md) (topology is T3), default `max_attempts`, and
Phase-2 measurement (`cost_per_solved_task` before the first honest lift interval).

[ADR-0007](0007-skill-identity-status-and-stats-split.md) already split immutable
`SkillVersion` from derived `SkillStats`. Growing application-session lists must not land
on the version document.

## Decision

1. Fifteen nodes remain the T3 topology. No `align_skills` node. Feature flags cannot grow
   the graph.
2. In-run `evolve` remains the §16 class repair. It MAY apply a Practice-published
   `PatchTemplate` via an O(1) lookup. It MUST NOT search, propose hypotheses, or hold a
   patch tree on `RunState`.
3. Fail-cluster authoring is a scheduled job / Practice curriculum. Success-path `distill`
   MUST NOT scan episodic memory for clusters.
4. `plan` MAY emit a deterministic `ExecutionGuide` (claim-conflict stitch). Default off.
   No happy-path LLM.
5. Distinct *application* sessions live on `SkillStats.apply_diversity` (T0, rebuildable).
   Authoring-time source ids stay frozen on `Provenance`. The diversity gate applies only
   at `approved`, not `candidate`/`shadow`.
6. Failure clusters are incremental rows upserted on `record_dead_end`. Practice reads
   `eligible`; it does not rescan blobs.
7. Improvement-plane jobs share a `JobQuota`. Priority is recertifier → curator retire →
   fail-cluster author → practice band → practice HEX (≤25% leftover) → compress.
8. Lint and compose review share one uses-DAG walk. Store re-lints only when
   `hygiene.lint_content_hash` disagrees with the current bytes.
9. Lineage revoke is a Recertifier queue plus an inverted source index. `record_dead_end`
   stays O(1).
10. Unit-level compress is a Curator proposal (steps are the units, cached-trace LOO,
    default off until a lift interval exists).

## Consequences

- Practice and Curator budgets must be real. HEX default-off until `practice_conversion`
  is a number.
- Console and Python lineage fields share one identity: authoring ids on the version,
  apply diversity on stats.
- `cluster_dead_ends` remains as a rebuild path when the incremental index is empty.
- Capability flags are T2; they cannot change `contracts.graph.NODES`.
