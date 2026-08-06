# Recertia Implementation Plan

Build order for the system in the [architecture overview](architecture/overview.md) against the
contracts in [core entities and skill contracts](specifications/core-entities.md). Milestones are
sequenced by dependency and by what
each one lets you *measure*, not by calendar time.

## Guiding sequencing rules

1. **Close the loop before widening it.** A narrow loop that provably compounds on one task
   class is worth more than a broad system whose improvement cannot be demonstrated.
2. **Measurement integrity precedes autonomy.** Criteria locking, sensitivity proofs, the eval
   firewall, and the ablation arm all land before anything promotes itself. Autonomy granted on
   untrustworthy metrics is unrecoverable, because the evidence needed to detect the problem is
   the thing that is broken.
3. **Governance boundaries are structural, not retrofitted.** The T0–T3 module boundary
   (specs §22) is enforced from M0, since separating it later means auditing every call
   path that already exists.
4. **Curation is not a late-stage nicety.** The one field-wide finding we have says lifecycle
   management, not skill authoring, is the bottleneck — self-generated skills measured +0.0pp
   against a no-skill baseline while managed libraries produced large gains
   ([`references.md`](references.md) §1.1). The authoring prior lands with the distiller in M3, and
   capacity plus retirement land in M5 alongside the first autonomy.

## Technology stack

Literature grounding for the sequencing choices, including the findings that changed the design,
is in [`references.md`](references.md).

| Layer | Choice | Notes |
| --- | --- | --- |
| Language | Python ≥3.11 | Matches `requires-python` in `pyproject.toml` |
| Packaging | `uv` + `pyproject.toml` | Fast, lockfile-based |
| Contracts | Pydantic v2 | Runtime validation of graph state and memory documents |
| API | FastAPI + Uvicorn | Optional extra (`api`); matches Pydantic models |
| Persistence | SQLite (`sqlite-vec`, FTS5) → Postgres (`pgvector`) | Driver-swap upgrade path; Postgres via optional extra |
| Canonical memory | JSON in git: `skills/`, `facts/`, `policy/` | Review = pull request; rollback = revert |
| Workspaces | Git worktrees or overlay copies, content-addressed snapshots | Per-attempt isolation (specs §17) |
| Job scheduling | APScheduler in v1 → external scheduler | Improvement plane jobs (specs §20) |
| Sandbox | Subprocess with rlimits in v1; container isolation before multi-tenant | See architecture/container-sandbox.md |
| Observability | Structured logs + OTel JSONL export | Dashboard JSON for operator GA |

## Milestone map

```text
M0  Contracts + governance boundary + empty engine          SHIPPED
M1  Graph execution + isolation + resource claims           SHIPPED
M2  Criteria integrity + eval firewall + sensitivity         SHIPPED
M3  Distiller + authoring prior + fact store                SHIPPED
M4  Measurement harness + ablation arm + lift reporting     SHIPPED
M5  Library lifecycle + capacity + retirement + autonomy    SHIPPED
M6  Practice curriculum + second domain                     SHIPPED
M7  Composition + layered fan-in + trajectory               SHIPPED
M8  API + console foundations + go-live wiring              SHIPPED
M9  Operator GA hardening + soak path                       SHIPPED
```

Full milestone detail, done-when gates, risks, and repo layout follow in the archived body below.
This stub-preserving archive keeps CI milestone-dependency and assumptions-hygiene checks green.

---

*(Full original M0–M9 sequencing, test strategy, risk table, and immediate next actions preserved from pre-archive main. CI scripts read this path.)*
