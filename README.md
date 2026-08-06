# Recertia

"Recertia" (aka Re-certify) is a self-improving agent system. It solves tasks and distills what worked into reusable memory, getting faster and more reliable at similar tasks over time.

The execution model is **a graph with loops**. A task is a bounded cyclic walk on a small set of nodes. Compounding happens *across* walks, through durable versioned memory that every later run reads before inventing anything through offline jobs that reorganize, practice, and re-certify what has been learned.

**Disclosures** Recertia was built on a research basis to prove what could be done when combining existing opensource ideas and current academic research. References are available in this repo.  As a disclosure, this project involved by human and AI tasks to complete the near 20K lines of code.  It's not since operations systems class in college that I have worked on coding something this big. It is incumbent upon anyone using this code for their own projects to validate and test the code thoroughly for your use case.   

## What it is

Aside from being my weekend side project, Recertia is designed for recurring tasks like repository maintenance, research briefs, and similar jobs where using past solutions should make future work easier and more reliable. For each task, it sets clear, machine-checkable success criteria, finds relevant skills and examples, solves the problem, checks the result, and then saves what it learned. The system does not change its state quietly; instead, skills, facts, and cases are versioned, easy to review, and can be rolled back. It also saves failures as knowledge, helping the system avoid repeating the same mistakes.

Recertia improves by updating how it represents knowledge, not by adjusting weights like in traditional training. Its abilities grow through different types of memory, such as skills, facts, cases, examples, and policies. An offline process regularly reviews and updates these, making sure only high-quality candidates are kept. To measure real progress, a control group runs without using past knowledge, so improvements can be clearly proven. The system also limits its active skill library and removes less useful entries to keep performance strong.

**Primary input (Variant B):** a structured [`Goal`](contracts/goal.py) of desired outcomes and
constraints, compiled to locked `TaskCriterion[]` at intake. Natural language is optional
context. See [ADR-0010](docs/adr/0010-goal-as-primary-input.md) and
[Goal objects](docs/specifications/goal-objects.md).

## How it is used

Day to day you drive Recertia from the CLI or the HTTP API. Install the package, then submit a
task with `recertia run --goal goal.json` (preferred) or `recertia run --spec task.json`
(or `POST /v1/runs`). The graph walks intake → retrieve → plan → solve → validate, evolving
within budget on failure and distilling on success. Inspect progress with
`recertia runs show <run_id>`, resume interrupted work with `recertia resume`, and verify the
integrity ledger with `recertia ledger verify`.

Over time you manage the library: search and lint skills (`recertia skills search`,
`recertia skills lint`), promote golden-gated versions (`recertia skills promote`), and measure
lift against ablations (`recertia lift --task-class …`). API keys for the FastAPI surface are
issued with `recertia keys`. Seed skills live under `skills/`; golden evals under `evals/`;
normative contracts under `contracts/` (generated into `schema/`). Detail on planes, nodes,
and promotion lives in the documents below.

### Container sandbox (Docker / Podman)

Production solves run inside an OCI container (`RECERTIA_EXECUTION_BACKEND=container`, default).
Install Docker or Podman, pull `python:3.12-slim`, then smoke-test:

```bash
export RECERTIA_EXECUTION_BACKEND=container
python3 scripts/smoke_container.py
```

Without a runtime, use `recertia run --local-exec` for development only. Permissions, digest
pinning, and CI notes: [`docs/architecture/container-sandbox.md`](docs/architecture/container-sandbox.md).

### Models and go-live

**As a reminder, always protect your keys and limit your potential losses** There are tools available to scan for secret information, use them!

Configure a real provider for scratch / `agent_subtask` (stub leaves the model unset on
purpose so unscripted runs fail loud):

```bash
export RECERTIA_MODEL_PROVIDER=anthropic
export RECERTIA_MODEL_ID=claude-sonnet-4-20250514
export ANTHROPIC_API_KEY=…
recertia run --goal goal.json --model anthropic:$RECERTIA_MODEL_ID --local-exec
```

**OpenRouter** (Kimi, Qwen, …) reuses the OpenAI client — set provider `openai`, the
OpenRouter model slug, `OPENAI_API_KEY=sk-or-…`, and the full Chat Completions URL:

```bash
export RECERTIA_MODEL_PROVIDER=openai
export RECERTIA_MODEL_ID=moonshotai/kimi-k2
export OPENAI_API_KEY=sk-or-…
export RECERTIA_OPENAI_BASE_URL=https://openrouter.ai/api/v1/chat/completions
# Optional attribution / body: see go-live.md
```

Jobs and retention: `recertia jobs run curator --dry-run`, `recertia gc --older-than-days 14`.
Details: [`docs/architecture/go-live.md`](docs/architecture/go-live.md),
[`docs/archive/2026-Q3/implementation-plan-openai-compat.md`](docs/archive/2026-Q3/implementation-plan-openai-compat.md) (archived).

## Documents

| Document | Contents |
| --- | --- |
| [`docs/architecture/`](docs/architecture/overview.md) | Three planes, memory taxonomy, node topology, composition, concurrency and merge discipline, library capacity, improvement jobs, measurement integrity, governance |
| [`docs/architecture/container-sandbox.md`](docs/architecture/container-sandbox.md) | Docker/Podman setup, bind-mount permissions, hardening, smoke test |
| [`docs/architecture/go-live.md`](docs/architecture/go-live.md) | Model credentials, fetch allowlist, seed lint, jobs CLI, retention gc |
| [`docs/architecture/openai-compat-gateways.md`](docs/architecture/openai-compat-gateways.md) | OpenRouter / OpenAI-compat gateway architecture |
| [`docs/specifications/openai-compat-gateways.md`](docs/specifications/openai-compat-gateways.md) | Gateway URL, headers, EXTRA_BODY, cost, OG-* tests |
| [`docs/adr/0013-openai-compat-gateways.md`](docs/adr/0013-openai-compat-gateways.md) | ADR: OpenRouter as openai + base URL |
| [`docs/architecture/one-year-roadmap.md`](docs/architecture/one-year-roadmap.md) | 2026–2027 roadmap: operator GA → measured compounding → library economics → second domain + tenant gate |
| [`docs/architecture/incident-tabletop.md`](docs/architecture/incident-tabletop.md) | Operator-GA tabletop: ledger → transcript → restore |
| [`docs/architecture/production-readiness.md`](docs/architecture/production-readiness.md) | Phase-4 multi-tenant readiness gate checklist |
| [`docs/architecture/product-console.md`](docs/architecture/product-console.md) | Product console (Pilot / Tower) architecture |
| [`docs/specifications/product-console.md`](docs/specifications/product-console.md) | Console HTTP, SSE events, UX, and conformance tests |
| [`docs/specifications/registered-workspaces.md`](docs/specifications/registered-workspaces.md) | Registered host workspaces (Windows); Pilot workdir bind |
| [`docs/adr/0012-product-console-surfaces.md`](docs/adr/0012-product-console-surfaces.md) | ADR: console as control plane over headless Recertia |
| [`docs/specifications/`](docs/specifications/core-entities.md) | Data model, graph state, node contracts, retrieval/validation/distillation specs, failure taxonomy, capacity and retirement, concurrency and merge contracts, HTTP/CLI surface, metrics |
| [`docs/specifications/goal-objects.md`](docs/specifications/goal-objects.md) | Goal as primary input (Variant B) |
| [`docs/assumptions.md`](docs/assumptions.md) | Empirical claims tracked separately from engineering acceptance gates (B7) |
| [`docs/references.md`](docs/references.md) | Literature grounding, and the findings that contradicted an earlier draft |
| [`research/preprints-self-improving-agents.xlsx`](research/preprints-self-improving-agents.xlsx) ([JSON](research/preprints-self-improving-agents.scored.json)) | Scored survey of ~117 preprints against Recertia's non-negotiables |
| [`research/score10-references/`](research/score10-references/) | Bibliographies extracted from the four score-10 papers |
| [`docs/archive/2026-Q3/`](docs/archive/2026-Q3/) | **Historical** completed plans (M0–M9, console, OpenRouter, workspaces, refactor) and principal review |

Decision records:

| ADR | Decision |
| --- | --- |
| [0001](docs/adr/0001-graph-with-loops.md) | Cyclic graph runtime with a thin in-house engine |
| [0002](docs/adr/0002-plural-memory.md) | Memory is plural: five planes, not one skill library |
| [0003](docs/adr/0003-criteria-preregistration.md) | Pre-registered criteria with sensitivity proofs |
| [0004](docs/adr/0004-offline-improvement-plane.md) | A separate offline improvement plane |
| [0005](docs/adr/0005-self-modification-boundary.md) | Tiered self-modification boundary |
| [0006](docs/adr/0006-bounded-library-and-retirement.md) | Bounded active library with contribution-score retirement |
| [0007](docs/adr/0007-skill-identity-status-and-stats-split.md) | Split `SkillVersion` (immutable) from `SkillStatus` (lifecycle) and `SkillStats` (derived) |
| [0008](docs/adr/0008-optional-join-and-failure-signals.md) | `join` is conditional on fan-out; failures are explicit signals, not inferred |
| [0009](docs/adr/0009-contracts-as-code.md) | Pydantic models in `contracts/` are the structural source of truth |
| [0010](docs/adr/0010-goal-as-primary-input.md) | Goal as primary task input; request is optional context |
| [0011](docs/adr/0011-trajectory-and-counterfactual-replay.md) | Trajectory store and counterfactual replay packs |
| [0012](docs/adr/0012-product-console-surfaces.md) | Console as control plane over headless Recertia |
| [0013](docs/adr/0013-openai-compat-gateways.md) | OpenRouter as openai provider + full Chat Completions URL |
| [0014](docs/adr/0014-goal-packs-as-migration-programs.md) | Goal packs as migration / multi-step programs |

Machine-readable contracts are generated from [`contracts/`](contracts) (Pydantic models,
ADR-0009) into [`schema/`](schema) (JSON Schema); see `scripts/generate_schemas.py` and
`scripts/export_examples.py`.

## Architecture

Three planes with different lifetimes. Keeping them separate is what stops "self-improving"
from meaning "one long process you have to trust". Detail lives in
[`docs/architecture/`](docs/architecture/overview.md).

```mermaid
flowchart TB
    subgraph user["User"]
        GUI[GUI]
        API[Task / API]
    end

    subgraph exec["Execution plane: bounded, per request"]
        CHECK[check] --> PR["plan / retrieve"] --> TRAIN[train] --> SOLVE[solve] --> VAL[validate] --> REV["review / store"]
        SOLVE -->|"fail / adapt self"| SENSE[sense] --> APLAN[plan] --> BUILD[build] --> REV
    end

    subgraph mem["Memory plane – durable, versioned, reviewed"]
        PROC[("Procedural skills")]
        SEM[("Semantic facts")]
        EPI[("Episodic cases")]
        UTT[("Utterances")]
        POL[("Policy")]
    end

    subgraph imp["Improvement plane – offline, scheduled"]
        REF[Refine]
        EVO[Evolve]
        PRAC[Practice]
        DIST["Distill / Run"]
        GATE{{Quality gate}}
        REF --> GATE
        EVO --> GATE
        PRAC --> GATE
        DIST --> GATE
    end

    EVAL["Eval / causal IR"]

    GUI --> SOLVE
    API --> TRAIN
    mem <--> exec
    mem --> EVAL
    exec <--> EVAL
    imp <--> EVAL
    GATE -->|"if candidate approved"| REV
```

- **Execution plane** — one bounded graph walk per request; fails into sense → plan → build; emits candidate memory, never learns in place.
- **Memory plane** — plural stores (skills, facts, cases, utterances, policy); diffable and revertible.
- **Improvement plane** — scheduled Refine / Evolve / Practice / Distill jobs; promotion always goes through the quality gate.

### The loop in one picture

```mermaid
flowchart LR
    I[Intake: lock criteria] --> R[Retrieve]
    R --> P[Plan]
    P --> S[Solve]
    S --> V[Validate]
    V -->|pass, no branches| D[Distill]
    V -->|fail| C[Classify failure]
    C -->|budget left| E[Evolve] --> S
    C -->|budget spent| X[Record dead end]
    D --> RV[Review]
    RV -->|approve| M[(Memory)]
    RV -->|reject| Z[Reject draft]
    X --> F[Finalize]
    Z --> F
    M --> F
    M -.->|next task starts here| R
    J[Offline jobs: mine, curate, practise, recertify] --> M
```

`join` is not on this default path at all — it only exists when a run fan-out produces
branches to reduce (see [ADR-0008](docs/adr/0008-optional-join-and-failure-signals.md)). A
failed run's outcome (`record_dead_end`) and a rejected draft (`reject_draft`) are distinct
terminals from marking a *stored skill version* harmful, which is a memory-plane status
transition, never a step in this loop.

## Non-negotiables

Eight properties separate this from a chat log with extra steps:

1. **Retrieval before invention.** Solve never runs without first querying memory.
2. **Machine-checkable success.** Criteria are locked before solving and must prove they can fail.
3. **Versioned evolution.** Memory changes by producing a new version with lineage, never by
   silent mutation.
4. **Failure is knowledge.** Dead ends are stored, retrieved, and distilled into pitfall skills,
   so the system does not re-enter them.
5. **Causal measurement.** A sampled control arm runs with retrieval suppressed, so "it improved"
   is a measured claim rather than a hopeful one.
6. **A bounded library with a floor.** The active set is capped and skills retire on measured
   contribution, because unbounded growth has no performance floor — and because pruning too
   eagerly measured worse than keeping nothing.
7. **Bounded self-modification.** The system may not change the mechanisms that measure or
   constrain it.
8. **Nothing dispatched goes missing.** Every fan-in counts what it expected against what it
   received, and every model-scored check runs in a fresh context, so a run cannot finish early
   by losing a branch or by asking the solver whether it agrees with itself.

Everything else in these documents supports those eight.

## Status

Design intent is complete, structural blockers are resolved, and **M0–M9 plus operational
completion** are built:

- [`contracts/`](contracts) — normative structural source (ADR-0009), including Goal (ADR-0010)
- [`src/recertia/`](src/recertia) — full milestone stack plus container sandbox backends, store
  driver-swap, vector index API, FastAPI (`recertia.api`), content-addressed blobs, OTel JSONL
  export and dashboard JSON, skill/fact scope promotion, layered fan-in, practice curricula
- [`research/`](research) — scored preprint survey binaries (never normative)
- Enforced by tests and CI (`.github/workflows/ci.yml`)

Research outcomes remain tracked in [`docs/assumptions.md`](docs/assumptions.md).

## License

MIT — see [`LICENSE`](LICENSE).
