# ADR-0014: Goal packs as migration programs (not mega-Goals)

- **Status:** proposed
- **Date:** 2026-08-02

## Context

Pilot Compose can return a draft `pack` of Goals for large briefs (re-architect, split,
migrate). Today that pack is ephemeral UX: apply one card → one `POST /v1/runs`. There is
no persisted program, no step dependency, and no workspace continuity across steps. Each
run still correctly locks its own `TaskCriterion[]` (ADR-0003, ADR-0010), but operators
building ~20k-LOC changes cannot express a migration as a sequence of proveable contracts.

Two failure modes push the wrong designs:

1. **Mega-Goal** — one Goal with dozens of desired states spanning characterization,
   structural moves, and behaviour locks. Criteria lock makes mid-run amendment illegal;
   the agent either thrash-fails or optimizes a vague composite.
2. **Prompt-only pack** — LLM returns three titles with `pytest -q` and no freeze zones.
   Looks like planning; measures nothing seam-specific.

Fan-out / `decomposition` inside a single run (ADR-0001, strategy hints) solves
*intra-run* branching, not *cross-run* migration programs with human gates between
stacked changes.

## Decision

1. **A Goal pack is a tenant-scoped program of ordered Goal steps**, not a new criterion
   type and not a second success contract inside one run.
2. **The atomic execution unit remains one Goal → one intake lock → one run**
   (ADR-0010 / ADR-0003 unchanged). Packs NEVER bypass `compile_goal` or auto-lock from
   Suggest.
3. **Packs are first-class persisted objects** (`GoalPack` + `GoalPackStep`) with optional
   `depends_on`, per-step freeze paths, and human confirm-before-submit by default.
4. **Workspace continuity is explicit and phased** (see architecture):
   - GP0: durable linear board; `handoff=none` with **external git metadata** and/or
     operator `workdir`, or `plan_only` (no pretend empty-workspace migrations).
   - GP0 default **`freeze_enforcement=advisory`** — freeze paths are hints until hard
     `must_not_modify` is honest.
   - Later: allowlisted copy-forward or git tip; **no auto-advance** in near-term scope.
5. **Suggest may propose multiple decompositions** (by risk / layer / seam). Choosing a
   decomposition instantiates a program; it does not silently rewrite an in-flight one.
6. **Program-level regression bars** are embedded DesiredState/Constraint lists merged at
   materialize; they still compile and lock **per run**.
7. **Compose remains AI-propose / human-apply** (ADR-0012 Pilot). Step bind uses
   `POST /v1/runs` then `bind_run_id` (or plan_only envelope).
8. **Public API name** is `/v1/programs` (`MigrationProgram`) to avoid collision with
   Tower `ReplayPack`; product copy may say “Goal pack”.

## Consequences

- Specs: [`../specifications/goal-packs.md`](../specifications/goal-packs.md).
- Architecture: [`../architecture/goal-packs.md`](../architecture/goal-packs.md).
- Build order: [`../implementation-plan-goal-packs.md`](../implementation-plan-goal-packs.md).
- GP0 implementation: `contracts/program.py`, `src/recertia/programs/`, `/v1/programs` routes.
- Skills / promotion / golden gate unchanged: programs produce ordinary runs.

## Alternatives considered

- **Encode migration as `strategy_hint=decomposition` only:** rejects human gates and
  stacked PR semantics; still one lock set.
- **Mutable criteria across pack steps inside one run:** violates ADR-0003.
- **External project tracker only (GitHub issues):** useful, but loses compile/preview
  integrity inside Recertia — hence `external_handoff` fields *plus* locked Goals.
- **Shared world-writable host checkout with no isolation:** incompatible with workdir
  sandbox rules and attempt isolation (operations §10.2).
- **Advertise hard freezes before snapshot `must_not_modify`:** rejected; trains false trust.
