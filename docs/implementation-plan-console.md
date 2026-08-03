# Product console implementation plan

Build order for the operator/reviewer console. Normative contracts:
[`specifications/product-console.md`](specifications/product-console.md). Architecture:
[`architecture/product-console.md`](architecture/product-console.md). Decisions:
[ADR-0012](adr/0012-product-console-surfaces.md).

Sequencing follows the same rules as [`implementation-plan.md`](implementation-plan.md):
close a narrow honest loop before widening; measurement integrity before autonomy; do not
bypass the golden gate for UI convenience. **Do not estimate calendar time** — milestones are
sized by dependency and what each one unlocks.

## Guiding rules (console-specific)

1. **Read path before write path.** List runs / skills / metrics before promote / decide.
2. **Poll before stream.** C0–C1 use request/response; C2 adds async + SSE.
3. **BFF may exist; browser must not hold long-lived API keys.**
4. **Git-native review is a valid Tower v1** — in-app inbox can trail PR integration.
5. **Single-operator console before multi-tenant chrome** (Phase-4 gate).
6. **Buy Grafana; build Goal form + queues.**

## Stack choices

| Layer | Choice | Notes |
| --- | --- | --- |
| Console API | Expand existing FastAPI (`src/recertia/api`) | Same contracts / auth story |
| Async worker | Process or thread pool → later external queue | Must share `GraphOrchestrator` code path |
| Events | JSONL event log per run + SSE | Derived from telemetry + trajectory |
| Proposals | SQLite or JSONL under `{runs_root}/proposals/` | Durable status machine |
| Frontend | TypeScript SPA (Vite + React) **or** HTMX/SSR | Pick one in C0; stay consistent |
| Human auth | OIDC (C3) | Dev BFF API-key bridge only for C0–C2 |
| Observability | OTel → Grafana | Console embeds summaries |

Frontend framework is an implementation detail; `/v1` JSON is the boundary (ADR-0009).

## Milestone map

```text
C0  Read-only Pilot + Ops summaries
C1  Tower actions (proposals, jobs, promote enqueue) + Git deep links
C2  Async runs + SSE + cancel
C3  OIDC human auth + RBAC
C4  Polish: templates, ReplayPack UX, Practice conversion, accessibility
C5  Multi-tenant console chrome (Phase-4 gated)
```

Each milestone lists **engineering gates** (merge requirements) and **explicit non-goals**.

### Implementation status

| Milestone | Engineering status | Notes |
| --- | --- | --- |
| C0 | Implemented | `GET /v1/runs`, transcript, skills, metrics; Goal preview; `/console` SPA |
| C1 | Implemented | Proposal store, jobs HTTP, promote → job + golden gate, search, ledger verify |
| C2 | Implemented | `mode=async` → 202 + worker; SSE events; cancel; quota release on finish |
| C3 | Implemented | Dev login + OIDC exchange; `/v1/me`; roles on T2 / promote |
| C4 | Implemented | Goal templates; tower-summary (practice/pressure); ReplayPack in proposal detail |
| C5 | Implemented (gated) | Tenant switcher + `RECERTIA_TENANT_SKILLS`; isolation tests — **ops gate** (soak / threat model) still required before multi-tenant GA claims |

Conformance: `tests/unit/test_product_console.py` (PC-1…PC-6). C5 UI must not be marketed as
multi-tenant-safe until production-readiness criteria pass.

**Registered workspaces (Pilot real-repo bind):** planned as RW0–RW2 in
[`implementation-plan-registered-workspaces.md`](implementation-plan-registered-workspaces.md)
(spec: [`specifications/registered-workspaces.md`](specifications/registered-workspaces.md)).
Does not reopen absolute `workdir` on create-run.

---

## C0 — Read-only console (Pilot + Ops)

**Goal:** An operator can submit a Goal from a form (via existing sync `POST /v1/runs` or
CLI bridge), browse runs and skills, and see honest metrics — without hand-editing JSON for
routine chores.

### Scope

**Backend**

- `GET /v1/runs` (cursor pagination; tenant filter)
- Extend `GET /v1/runs/{id}` with spend + manifest summary fields if missing
- `GET /v1/runs/{id}/transcript`
- `GET /v1/skills`, `GET /v1/skills/{id}/versions/{v}`
- `GET /v1/metrics/report`, `GET /v1/metrics/canary`

**Frontend**

- Goal form + JSON preview + submit (sync)
- Runs list + run detail (route log, transcript viewer)
- Skills list + skill detail (read-only)
- Metrics page (`unavailable` reasons visible)

**Auth:** server-side BFF with operator-issued API key **or** local-only binding to
filesystem stores for single-host demos. Document the threat model: C0 is not internet-facing
multi-user.

### Engineering gates

- PC-1 (tenant isolation on list runs)
- PC-5 (metrics honesty)
- PC-6 (Goal preview validation)
- UI loads on desktop viewport; Goal submit creates a run visible in the list

### Non-goals

- SSE, cancel, OIDC, proposal decisions, promote from UI

### Unlocks

Operators stop living in raw JSON for day-to-day chores; soak/metrics become visible.

---

## C1 — Tower: proposals, jobs, promote enqueue

**Goal:** Reviewers can see improvement-plane output and act without SSHing to a host.

### Scope

**Backend**

- Durable proposal store; jobs persist proposals on run
- `GET/POST /v1/proposals…`, decision endpoint
- `GET/POST /v1/jobs…`
- `POST /v1/skills/…/promote` → async job record (may run in-process initially)
- `POST /v1/skills/search`
- `GET /v1/ledger/verify`
- Optional: attach `git_pr_url` when a deployment opens PRs for skill diffs

**Frontend**

- Proposal inbox + detail (ReplayPack summary)
- Jobs panel (trigger Practice/Curator/mine; show last result)
- Promote button → job status + golden failure ids
- Deep link to Git PR when present

### Engineering gates

- PC-2 (promote does not skip golden gate)
- PC-3 (decision ledger actor)
- Job trigger with `dry_run=true` emits proposals without library mutation
- Rejected proposal cannot be silently re-applied as approved

### Non-goals

- Live token streaming; multi-tenant switcher; T2 policy editor beyond correction proposals

### Unlocks

Tower workflow; closes the “jobs only exist as CLI stdout” gap.

---

## C2 — Async execution + live events + cancel

**Goal:** Pilot feels live without holding an HTTP request open for the whole graph.

### Scope

**Backend**

- `mode=async` on create → `202` + worker
- Per-run event log; SSE `GET /v1/runs/{id}/events` with resume cursor
- `POST /v1/runs/{id}/cancel` cooperative at node boundary
- Preserve sync mode for CLI/scripts

**Frontend**

- Live run view (event timeline)
- Cancel control
- Automatic fallback to polling

### Engineering gates

- PC-4 (SSE reconnect semantics)
- Cancelled run leaves checkpoints consistent; resume behaviour documented
- Async and sync runs share identical ledger/manifest invariants
- Load test smoke: N concurrent async runs respect `QuotaStore` / in-flight limits

### Non-goals

- Multi-region workers; exactly-once cross-process queues (at-least-once + idempotent
  handlers is enough)

### Unlocks

Real Pilot UX; foundation for multi-user later.

---

## C3 — Human authentication and RBAC

**Goal:** Console users are people, not shared API keys in browser storage.

### Scope

- OIDC login (BFF) + `/v1/me`
- Roles: `operator`, `reviewer`, `admin`
- Map identity → `tenant_id` (single tenant default)
- API keys remain for automation; document separation
- Audit: human actor on proposal decisions and promote triggers

### Engineering gates

- Unauthenticated browser cannot call protect routes
- `operator` cannot decide T2 proposals
- Session fixation / CSRF protections on BFF
- Key material never shipped to SPA bundles

### Non-goals

- Full SCIM directory sync; fine-grained ABAC

### Unlocks

Safe sharing of a console URL inside a team.

---

## C4 — Operator polish

**Goal:** Console is the default daily driver for single-operator GA workflows.

### Scope

- Goal templates library + “duplicate last Goal”
- ReplayPack visualization (treatment vs counterfactual FAS; status string)
- Practice conversion and active-cap pressure panels
- Accessibility pass (keyboard, contrast, confirm dialogs)
- Optional CLI twins: `recertia proposals queue`, `recertia review decide`

### Engineering gates

- Template Goals pass Goal validation and a golden smoke for one seed chore
- Accessibility smoke (axe or equivalent) on Pilot + Tower primary pages
- Docs: go-live section “Console” pointing operators here first

### Non-goals

- Mobile-native apps; marketplace of third-party templates

---

## C5 — Multi-tenant console chrome (Phase-4 gated)

**Goal:** Tenant switcher and org-aware library views — **only if**
[`architecture/production-readiness.md`](architecture/production-readiness.md) multi-tenant
GA criteria are met.

### Scope

- Tenant switcher from `/v1/me`
- Tenant-scoped skills/facts roots (or explicit shared org library with redaction)
- Quota admin views
- Threat-model sign-off checklist linked from console admin

### Engineering gates

- Cross-tenant run/proposal/skill leakage tests (release blockers)
- Planted-secret crossing still green under console-driven promote/upscope
- Written threat model signed by someone other than its author

### Non-goals if gate fails

- Ship C5 UI that implies multi-tenant safety — defer and keep single-operator product

---

## Dependency graph

```text
C0 ──► C1 ──► C2
 │      │
 │      └────► C4
 └──► C3 ─────► C4
                 │
                 └─► C5 (requires Phase-4 readiness gate, not only C4)
```

C3 may proceed in parallel with C2 after C0. C5 is gated by research/ops criteria outside
this plan (`a1`, soak weeks, signed threat model).

## Relationship to M0–M9 and the one-year roadmap

| Existing asset | Console use |
| --- | --- |
| M0–M9 runtime | Unchanged execution core |
| Go-live / jobs / metrics | C0–C1 wrap these |
| Trajectory / ReplayPack | C1–C4 Tower evidence |
| Production readiness | Gate for C5 |

Console work MUST NOT mark assumptions `a1`/`a2`/`a4` as `supported` without real traffic
intervals (B7).

## Documentation deliverables per milestone

| Milestone | Docs update |
| --- | --- |
| C0 | `go-live.md` Console section; OpenAPI or schema notes for new routes |
| C1 | Proposal store layout; update promotion-api aspirational table → implemented |
| C2 | Async run semantics; event types appendix |
| C3 | Auth threat model paragraph in production-readiness |
| C4 | Operator tutorial replacing “edit JSON” as primary path |
| C5 | Tenant topology diagram; readiness checklist status |

## Out-of-box delivery options (allowed substitutes)

These satisfy milestone *intent* when explicitly documented as the chosen path:

| Milestone intent | Allowed substitute |
| --- | --- |
| C1 in-app proposal inbox | GitHub/GitLab PR queue as Tower, with console deep links only |
| C0 metrics page | Grafana board + console link-out (summary cards still required) |
| C2 SSE | Short-poll ≤2s if SSE blocked by infra; same event log schema |

Substitutes MUST preserve PC-* conformance tests where applicable.

## Staffing sketch (roles, not headcount-weeks)

- One engineer owning API + worker invariants
- One engineer owning Pilot/Tower UI
- Shared: reviewer for golden-gate / auth boundaries
- Part-time: design for Goal form clarity (high leverage)

Avoid staffing a separate “metrics product” team; buy that surface.
