# Goal packs / migration programs — implementation plan (revised)

Build order after principal review of ADR-0014. Normative:
[`specifications/goal-packs.md`](specifications/goal-packs.md). Architecture:
[`architecture/goal-packs.md`](architecture/goal-packs.md).

**Public API name:** `/v1/programs` (`MigrationProgram`). Product copy may say “Goal pack”.
Distinct from Tower `ReplayPack`.

## Guiding rules (revised)

1. One Goal → one lock → one run remains the execution atom.
2. **Do not advertise hard freezes until `freeze_enforcement=hard` is honest** (snapshot /
   digest `must_not_modify`). GP0 default is **`advisory`**.
3. **GP0 execution requires** `plan_only`, **or** `workdir`, **and/or** `external_handoff`
   (branch / PR / SHA). Empty isolated workspaces are not a migration handoff.
4. **Linear ordinals only** in GP0 (no DAG).
5. **`run_ids[]` + `current_run_id`**; never overwrite attempt history.
6. Persist board before copy-forward / git tip / auto-advance.
7. Auto-advance is **deferred** (not GP2 scope anymore).
8. Types live in `contracts/program.py` (ADR-0009).

## Milestone map (revised)

```text
GP0   Durable linear program board + preview + bind-run (SHIPPING)
GP0.5 Probe (read-only) + Compose decompositions wiring
GP1   freeze_enforcement=hard + budget rollup + skip
GP2   copy_forward (allowlisted paths) OR git_tip — pick one; no auto-advance
```

| Milestone | Status / unlock |
| --- | --- |
| **GP0** | Implemented: contracts, store, `/v1/programs`, materialize, stress, bind flow, tests |
| GP0.5 | Optional probe + suggest `decompositions[]` |
| GP1 | Real freeze + pack budget + skip |
| GP2 | Continuity handoff (prefer git_tip over whole-tree copy) |

---

## GP0 — shipped in this change

### Scope delivered

- `contracts/program.py` — `MigrationProgram`, `MigrationStep`, `ExternalHandoff`,
  `budget_from_goal_constraints`
- `src/recertia/programs/` — store, materialize (program bar merge), stress, GP0 prereqs
- HTTP: create/list/get/accept/abandon, step patch (immutable after bind), preview, run
  (plan_only envelope **or** `bind_run_id`)
- Default `freeze_enforcement=advisory` (info warning; no fake `must_not_modify`)
- Linear predecessor gate; idempotent bind; tenant isolation
- Tests: `tests/unit/test_migration_programs.py`

### Operator flow

1. `POST /v1/programs` with steps → `POST …/accept`
2. `POST …/steps/{id}/preview` → inspect compiled criteria
3. `POST …/steps/{id}/run` (`plan_only` or envelope) → `POST /v1/runs` with `run_create`
4. `POST …/steps/{id}/run` with `bind_run_id` (+ workdir or external_handoff)

### Explicit non-goals (still)

- DAG `depends_on` execution
- Auto-advance
- Whole-tree copy-forward
- Claiming freeze is enforced while advisory
- Console program board UI (API-first; Pilot board follows)

---

## GP0.5 — probe + propose quality

- `POST /v1/goals/probe` allowlisted read-only inventory
- Suggest returns `decompositions[]` using slot templates (`by_risk`, `by_seam`)
- Keep single propose surface (`/v1/goals/suggest`); no duplicate `/v1/packs/propose`

## GP1 — honest constraints

- Snapshot/digest `must_not_modify`; allow `freeze_enforcement=hard`
- Pack budget remaining; skip with note
- Conformance GP-T7–T10 as applicable

## GP2 — continuity

- Prefer **git_tip** + registered binding over whole-tree copy_forward
- If copy_forward: git-tracked / allowlist + size caps only
- **No auto-advance** in this milestone

## Success metrics (feature health)

- First-bind step success rate
- Share of steps without `generic_pytest_only`
- Freeze-violation catch rate once hard enforcement ships
- Packs completed without skip

## Out of order / do not do

- Mega-Goal “raise K”
- Suggest auto-submit of all steps
- Shared live workdir across steps
- Pack status as promotion signal
- Advertising hard freezes before GP1
