# Product console implementation plan

Build order for the operator/reviewer console. Normative contracts:
[`specifications/product-console.md`](specifications/product-console.md). Architecture:
[`architecture/product-console.md`](architecture/product-console.md). Decisions:
[ADR-0012](adr/0012-product-console-surfaces.md).

## Guiding rules (console-specific)

1. **Read path before write path.** List runs / skills / metrics before promote / decide.
2. **Poll before stream.** C0–C1 use request/response; C2 adds async + SSE.
3. **BFF may exist; browser must not hold long-lived API keys.**
4. **Git-native review is a valid Tower v1** — in-app inbox can trail PR integration.
5. **Single-operator console before multi-tenant chrome** (Phase-4 gate).
6. **Buy Grafana; build Goal form + queues.**

## Milestone map

```text
C0  Read-only Pilot + Ops summaries                         Implemented
C1  Tower actions (proposals, jobs, promote) + Git links    Implemented
C2  Async runs + SSE + cancel                               Implemented
C3  OIDC human auth + RBAC                                  Implemented
C4  Polish: templates, ReplayPack UX, accessibility         Implemented
C5  Multi-tenant console chrome (Phase-4 gated)             Deferred
```

## C0–C4 — shipped

Read-only Pilot + Ops; proposal store and promote enqueue; async runs with SSE; OIDC + RBAC;
polish for templates and ReplayPack UX. Console work MUST NOT mark assumptions `a1`/`a2`/`a4`
as `supported` without real traffic intervals (B7).

## C5 — multi-tenant (Phase-4 gate)

Cross-tenant leakage tests; planted-secret crossing; signed threat model. Do not ship C5 UI
that implies multi-tenant safety until the gate passes.

## Relationship to M0–M9

Console wraps the existing runtime; go-live / jobs / metrics; trajectory / ReplayPack evidence.
Production readiness is the gate for C5.
