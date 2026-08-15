# ADR-0001: Cyclic graph runtime with an in-house engine

- **Status:** accepted
- **Context date:** repository bootstrap, before any runtime code exists

## Context

Recertia's learning loop (retrieve → solve → validate → distill → store, with revision
cycles) is inherently cyclic. Three implementation shapes were considered:

1. **Nested control flow in a solver** — retries as loops inside a function.
2. **A DAG pipeline runner** (Airflow/Prefect style) with re-invocation for retries.
3. **A cyclic state graph** with typed state, conditional edges, and checkpoints.

An orthogonal question: build the graph engine or adopt an agent framework
(LangGraph and similar) that provides one.

## Decision

Adopt shape 3, a cyclic state graph, and implement a **thin in-house engine** over an
explicit node/edge registry.

## Rationale

Against shape 1: retries hidden inside a solver make budgets ad hoc, make partial
progress unresumable, and make the routing decisions that matter most — "was a skill
applied, and why did we retry" — invisible to auditing and to the eval harness.

Against shape 2: DAG runners forbid cycles by design. Expressing revision as re-running
the whole DAG loses in-run state and conflates the inner loop with scheduling.

For an in-house engine: the required surface is small — typed state, conditional edges,
per-node checkpoint, budget hooks. Owning it keeps the state schema (which is also the
audit record and the replay format) under our control, avoids coupling promotion policy
to a third party's abstractions, and keeps determinism-given-node-outputs achievable,
which is what makes replay testing possible. Frameworks are a reasonable fit for the
control flow but would own the state and persistence formats that the rest of this
system specifies precisely.

## Consequences

- The engine must ship with checkpointing and budget enforcement from M0; these are not
  later additions.
- Node implementations must be pure with respect to state: `(state) -> (delta, route)`.
  All I/O goes through injected services, so nodes are unit-testable without a model.
- We carry the maintenance cost of the engine. Accepted because the surface is narrow and
  frozen by the state schema in `specifications/graph-execution.md`.
- If the engine's scope grows beyond routing, persistence, and budgets, that is the
  signal to revisit this decision rather than to keep extending it.
