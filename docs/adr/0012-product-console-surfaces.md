# ADR-0012: Product console as a control plane over headless Recertia

- **Status:** proposed
- **Date:** 2026-08-01

## Context

Recertia today is a CLI- and API-key-driven headless runtime. Operators author Goals as JSON,
inspect runs with `recertia runs show`, and trigger improvement jobs from the CLI. A full
product console — runs browser, skill library, proposal review queue, Practice/Curator
panels, human auth, live streaming — is a natural next surface, especially for Phase-4
multi-tenant readiness. The risk is building a monolithic admin SPA that re-implements Git
review, Grafana, and the orchestrator, while bypassing the measurement and golden-gate
invariants the system exists to protect.

## Decision

1. **Recertia remains the headless control plane.** The console is a client of expanded
   `/v1` APIs and event streams; it does not embed graph execution in the browser.
2. **Two human surfaces, deliberately different tempos:**
   - **Pilot** — Goal authoring and live/async run observation (operator workflow).
   - **Tower** — Library, proposals, Practice/Curator, retirement, canaries (reviewer /
     curator workflow).
3. **Skill promotion stays golden-gated.** The console may *trigger* `promote_to_approved`
   and display results; it MUST NOT write `lifecycle=approved` directly (ADR-0004, M7).
4. **Default review path for library mutations is Git-native** (PR / diff on
   `skills/` / `facts/` / `policy/`). An in-app proposal inbox is additive for operators who
   lack git workflow; it records the same ledger actions.
5. **Human auth ≠ API keys.** Console users authenticate via OIDC (or equivalent SSO).
   API keys remain service accounts for automation (`runs`, `blobs`, `metrics`, `exec`).
6. **Live UX requires async execution + an event log.** Streaming MUST NOT be bolted onto
   today’s sync `POST /v1/runs` response; introduce enqueue + worker + SSE (or WebSocket)
   over trajectory/telemetry events.
7. **Single-operator console precedes multi-tenant chrome.** Tenant switcher, org RBAC, and
   isolated libraries wait on the Phase-4 gate.

## Consequences

- Specs for console HTTP, events, and UX live in
  [`../specifications/product-console.md`](../specifications/product-console.md).
- Observability dashboards SHOULD be bought (Grafana / OTel) rather than rebuilt; the
  console embeds links or light panels, not a second metrics product.
- Measurement integrity (B7, ablation, golden gate) is unchanged: the console is a UI over
  those controls, never a bypass.
