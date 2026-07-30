# ADR-0002: Memory is plural, not a single skill library

- **Status:** accepted
- **Supersedes part of:** the single-store assumption in the first architecture draft

## Context

The initial design had exactly one durable store: a library of procedural skills. Two
problems followed from that, and both are structural rather than tuning issues.

First, any knowledge that is not a procedure had nowhere to live. "Migrations run through
`scripts/migrate`", "this test suite flakes under parallelism", "package X is pinned
deliberately" are all durable, reusable, and expensive to rediscover — but none of them has
steps or an exit code, so none can be a skill. They were therefore rediscovered on every run.

Second, failure was discarded. Failed runs routed to `quarantine`, which recorded that
something went wrong and kept no reusable account of *what was tried and why it failed*. That
throws away a large share of the available signal, and it guarantees the system re-enters dead
ends it has already paid to discover.

## Decision

Split durable memory into five planes with distinct write paths, read paths, and trust
semantics: **procedural** (skills), **semantic** (facts and invariants), **episodic** (cases,
including failed attempts and dead ends), **affordance** (learned tool and environment
behaviour), and **policy** (meta-parameters governing the system's own behaviour).

`retrieve` becomes a federated query returning a typed bundle across planes, with per-element
provenance and trust.

## Rationale

Each plane has a genuinely different lifecycle, which is the test for whether a split is real
rather than cosmetic:

- Skills change through reviewed, validated versions.
- Facts are asserted and occasionally verified, and they constrain how procedures run.
- Cases are append-only and never promoted; their value is analogy and avoidance.
- Affordance data changes continuously from telemetry with no task occurring at all.
- Policy governs the system and is therefore governed in turn (ADR-0005).

Forcing all five through skill schema and skill promotion would either corrupt the skill
lifecycle with things that cannot be validated the same way, or lose the information.

## Consequences

- Retrieval, indexing, and the distiller all become multi-target: `distill` emits facts and
  affordance updates alongside a skill draft.
- Negative knowledge needs a retrieval path and an `evolve` consumer, not just storage.
- Trust and provenance must be per-element, since a low-confidence fact and a high-trust
  skill can appear in the same bundle.
- Injection surface widens: more model-authored content reaching solver context, which is why
  memory-as-data discipline is a hard rule rather than a guideline.
- Cost: five stores to index, curate, and scope. Accepted because four of the five are
  cheap-to-write derived data, and the alternative is paying to rediscover them per run.
