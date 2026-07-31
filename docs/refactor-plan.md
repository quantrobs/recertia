# Repository refactor plan

The previous version of this plan moved files. That is necessary and is still R0 below.
It is not the problem.

The problem was that the design, as written, **could not be implemented without inventing
answers the docs pretended to have already given**. Several load-bearing contracts were
internally contradictory; the milestone order asked M0–M3 to satisfy MUSTs that only existed
in M4–M6; and "the schema is the source of truth" was false — the canonical skill example
validated against the schema while missing half the fields the prose required for an
`approved` skill.

This plan is the work that has to happen **before M0 writes a line of runtime code**. It
is a design refactor with a small amount of repo hygiene attached, not the reverse.

Originally verified against `main`. Claims below cite concrete fields and routing
predicates, not vibes.

## Resolution status

**B1–B5 are resolved.** They were data-model and routing contradictions, fixed together
because R1's own ordering rule (§3) says B3/B4 (routing) and B1/B5 (data model) have to land
before B2 (criteria timeline) can be stated meaningfully. All five are now: an ADR, a
Pydantic model in [`contracts/`](../contracts), a generated schema, and a passing test in
[`tests/contracts/`](../tests/contracts) that would fail if the contradiction came back.

**B6 is resolved** in `implementation-plan.md`'s M0–M3 (pulled-forward mechanisms) and M4/M5
done-whens (split engineering gate from research outcome). **B7 is resolved**: the split is
written into M4/M5/M9's done-whens, and [`docs/assumptions.md`](assumptions.md) now exists,
migrating [`references.md` §8](references.md#8-open-questions-the-literature-does-not-settle-for-us).

**R2 is done** — `contracts/`, `scripts/generate_schemas.py`, `scripts/export_examples.py`,
semantic profiles in `contracts/profiles.py`, and now the `src/fandea/` M0 walking-skeleton
runtime (graph engine, all fifteen nodes, hash-chain ledger, workspace snapshotting, the
operation ledger, the T0–T3 import-boundary test, and the CLI) all exist and are tested — see
`docs/implementation-plan.md` M0. **R3 is done**: route completeness, schema-drift, semantic-profile checks, cross-refs,
milestone-dependency, assumptions-hygiene, and the full `src/fandea/`/`contracts/` test suite
run as [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) on every push and PR. R4
(doc split) and R5 (branch cleanup) are done. R0 (research/ binaries) is done.

| Blocker | ADR | Contracts | Tests | Docs updated |
| --- | --- | --- | --- | --- |
| B1 — SkillVersion split | [ADR-0007](adr/0007-skill-identity-status-and-stats-split.md) | `contracts/skill.py`, `contracts/status.py`, `contracts/stats.py` | `test_semantic_profiles.py`, `test_structural_validity.py` | specs §1–§2, architecture §5.4 §7.1 §9 |
| B2 — criteria timeline | [ADR-0003 amendment](adr/0003-criteria-preregistration.md) | `contracts/criteria.py` | `test_criteria_timeline.py` | specs §15.1 §15.4, architecture §11.1 |
| B3 — conditional join | [ADR-0008](adr/0008-optional-join-and-failure-signals.md) | `contracts/graph.py`, `contracts/branch.py` | `test_route_completeness.py` | specs §4 §4.1, architecture §5.1, README diagram |
| B4 — FailureSignal + quarantine split | [ADR-0008](adr/0008-optional-join-and-failure-signals.md) | `contracts/failure.py` | `test_route_completeness.py` | specs §4 §16 §21, architecture §5.1 |
| B5 — contracts as code | [ADR-0009](adr/0009-contracts-as-code.md) | all of `contracts/`; `contracts/profiles.py`, `contracts/examples.py` | `test_examples.py`, `test_schema_generation.py`, `test_structural_validity.py` | specs (intro + throughout), implementation-plan (repo layout, CI invariants) |
| B6 — milestone dependency order | — (prose fix, no new decision) | — | `scripts/check_milestone_deps.py` | implementation-plan M0–M3 |
| B7 — research vs. engineering gates | — (prose fix, no new decision) | — | `scripts/check_assumptions_hygiene.py` | implementation-plan M4 M5 M9; `assumptions.md` (new) |

B1–B7 and R0–R4 are closed. This document's remaining live content is the secondary debt
table in §1 (S3/S6–S8 done; S1/S2/S4/S5 done — see Status column) and optional R5 hygiene.

---

## 0. Diagnosis: seven blockers (historical — resolved above)

(Numbering starts at 0 deliberately, unlike the architecture and specifications topics' 1-index:
"0" marks diagnosis-before-any-fix. If a cross-reference checker is ever generalised to this
document, treat that as intentional, not a bug to "fix" by renumbering.)

### B1. `SkillVersion` is immutable and continuously rewritten

`specifications/core-entities.md` §1: `SkillVersion` is "**Immutable once written**." M1 refuses any
rewrite of an existing version. Yet `skill.schema.json` embeds in that same document:
`lifecycle`, `active`, `trust`, `contribution`, `retirement`, and certification fields —
all of which change after the version is written.

Every promotion, trust update, bench, restore, and recert is therefore an illegal rewrite
of an immutable object. An implementer will either violate immutability on day one or invent
a side table the docs never named.

**Fix:** split the artifact.

| Record | Mutability | Holds |
| --- | --- | --- |
| `SkillVersion` | Immutable, content-addressed | `skill_id`, `version`, intent, steps, criteria, provenance, parameters |
| `SkillStatus` | Append-only events → current projection | lifecycle transitions, `active`, retirement, certification |
| `SkillStats` | Derived, rebuildable (T0) | trust, contribution, applications |

`active` is derived from the active-set record, not stored on the version. The schema becomes
three documents; the prose stops saying "immutable" about a bag that includes counters.

### B2. Run criteria and skill-certification criteria are the same type

`intake` locks criteria before `retrieve` and `plan` (§4, §15). Skill-inherited criteria are
listed as a lock source — but no skill has been chosen yet. Distillation in M3 authors
criteria *after* solving, while §2.1 requires required criteria to be `preregistered`.

An applied skill cannot contribute its criteria before selection. A newly distilled skill
cannot honestly claim its post-hoc criteria were preregistered. The scratch-run → candidate
path that is the system's core claim is undefined.

**Fix:** two types.

- `TaskCriterion` — locked at intake for *this run*; may come from the caller, a task-class
  template, or (after plan) the chosen skill's *certification* criteria projected into the run.
- `SkillCertificationCriterion` — authored at distill time; validated prospectively on
  independent fixtures before the skill may leave `candidate`. "Preregistered" means
  registered before *certification runs*, not before the transcript that produced the draft.

The run's locked set and the skill's certification set are allowed to differ. Pretending
they are one thing is what made the timeline impossible.

### B3. Every run must pass through `join`, which has no singleton semantics

Architecture §5.1 routes `validate → join` unconditionally. Specs §4 define `join` only in
terms of branches, portfolio selection, and decomposition synthesis. The routing predicate
tests `merge_audit.complete`, but `MergeAudit` has no `complete` field — it has
`action ∈ {proceeded, flagged, failed}`. Fan-out itself is deferred to M6.

M0–M5 therefore have no specified route from a successful single-attempt validation to
`distill`.

**Fix — resolved as Option 1, not left open:** ordinary runs route
`validate → distill | classify_failure`; `join` exists only when `branches` is non-empty
([ADR-0008](adr/0008-optional-join-and-failure-signals.md)). This was not a coin flip between
two equally-good options — [`README.md`](../README.md)'s simplified loop diagram already drew
`V -->|pass| D` with no `join` on the default path, before this plan was written. Option 2
(universal singleton `ExecutionGroup`) would have required rewriting the one diagram every
other document treats as ground truth, for a M6 mechanism M0–M5 never exercise.
`architecture/task-plane.md` §5.1 and `specifications/graph-execution.md` §4/§4.1 were the
documents that were wrong; README was not.

### B4. Most failure classes cannot legally reach `classify_failure`

Preconditions for `classify_failure`: "**Some required criterion failed**." But
`environment`, `tool`, and `budget` failures occur before or instead of validation; a
`merge` gap need not produce a failed criterion; `review → quarantine` fires with no
`failure` set at all, violating `quarantine`'s own precondition.

"Quarantine" also conflates three different acts: record a failed run, reject a draft, and
mark a stored skill version harmful.

**Fix:**

- Introduce `FailureSignal` emitted by orchestrator / solver / validator / join — not only
  by criterion failure.
- Explicit error edges into `classify_failure` that do not require a result vector.
- Split terminals: `record_dead_end` (run), `reject_draft` (review), `quarantine_version`
  (stored skill). Stop overloading one node.

### B5. Schemas do not encode the normative rules, and win conflicts anyway

The refactor plan previously said "schemas win on conflict." Today that would make the
wrong thing win.

The canonical skill example in specs §2 **validates** against `skill.schema.json` while
missing prose-required `preregistered`, `sensitivity_proof`, `certification`,
`hygiene.secret_scan`, and `provenance.curation`. The run schema omits `criteria` and
`advisory_criteria` from `RunState`, omits `Branch.budget`, and requires only
`run_id` / `task` / `budget` / `spent` — so an empty budget object is a valid run.

Contract CI that only runs `Draft202012Validator` will be green while accepting states the
prose forbids.

**Fix:** ownership, then tooling.

1. **Prose owns semantics. Schemas own structure.** Conflicts are bugs in the schema, not
   licences to ignore the prose.
2. One generated structural model (Pydantic → JSON Schema, or the reverse — pick in R2).
3. **Semantic profiles** on top: `approved-skill`, `candidate-skill`, `checkpointed-run`,
   each a separate validator that checks the MUSTs the structural schema cannot express.
4. CI runs both. The canonical examples must pass their lifecycle profile, not merely parse.

### B6. Milestones require mechanisms scheduled after they are needed

| Early need | Deferred to | Breakage |
| --- | --- | --- |
| Required criteria must carry sensitivity proofs (§6) | Proofs land in M3 | M0–M2 required criteria are definitionally advisory |
| Retrieval filters to the active set (M1) | Active-set management in M5 | M1 either retrieves everything or invents a cap |
| M1 applies `approved` hand-authored skills | Hygiene in M3; golden-set gate in M4 | Approving the seed library violates §8 |
| M3 reviewer approves a candidate | Golden regression required before any approval (§8) | The core claim demo is non-compliant |
| M0 resumes after process death | No crash-consistency / idempotency model anywhere | Replay duplicates tool and ledger effects |

**Fix:** pull the *minimum* of each mechanism into the first milestone that needs it.
Experimentation, automatic retirement, and dashboards stay late. Seed-library approval,
sensitivity execution, active assignment (even if "all approved skills are active"), and a
golden regression runner move forward. Specify at-least-once node execution with stable
operation ids before claiming kill/resume.

### B7. Research thresholds have been promoted to acceptance gates

Several design-shaping citations are marked `[B]` (not independently verified). Ratchet's
own cold-start regime is admitted to be under-evidenced for our traffic. Yet ADR-0006 and
specs §24 freeze their thresholds as defaults, M5 requires reproducing a paper's
underperformance result, and M4 requires `causal_lift` with an interval excluding zero.

A correct implementation can fail a milestone because the *product hypothesis* is false, or
because traffic is too thin to estimate lift. That is not an engineering gate.

**Fix:** split the registers.

- **Engineering acceptance:** the harness measures correctly, reports "not established"
  when intervals span zero, enforces structural invariants (finite cap, non-judge
  contribution, etc.).
- **Research outcomes:** tracked in an assumptions register with evidence status; empirical
  thresholds remain T2 policy defaults, not architectural truths; M4/M5 done-whens stop
  requiring the world to cooperate.

---

## 1. Secondary debt (real, not blockers)

These hurt, but they do not strand M0 by themselves. Schedule after the blockers, or fold
into the same PR when touching that surface.

| ID | Debt | Sharper fix than "document it" | Status |
| --- | --- | --- | --- |
| S1 | Step DAG has `depends_on` but no declared outputs / bindings; fake-edge test is unenforceable | Derive edges from typed `input_bindings` → `step.output`; drop free-floating `depends_on` as authoring input | **Done** — `contracts/skill.py` `Step`/`StepOutput`/`InputBinding`; edges from `input_bindings` only; `tests/contracts/test_step_bindings.py` |
| S2 | `retrieve` "must not execute" but preconditions include `command_succeeds` | Registered read-only probes with budget and evidence, not arbitrary commands | **Done** — `Precondition.kind` includes `probe` (not `command_succeeds`); `src/fandea/retrieval/preconditions.py`; `tests/unit/retrieval/test_preconditions.py` |
| S3 | `Branch` has no status, spend, transcript, snapshot; schema omits `budget` | `BranchState` + `BudgetLease` against a parent ledger; reserve join overhead | **Done, as a side effect of B3** — `contracts/branch.py`'s `BranchState` has all of status/spend/transcript/snapshot/budget; `schema/branch.schema.json` generated |
| S4 | `skill_contribution` subtracts a class baseline from a non-randomly selected skill | Three quantities, stored once: predictive trust, class-level retrieval effect (ablation), per-skill effect (shadow/suppression) | **Done** — `PredictiveTrust`, `RetrievalAblationEffect`, `Contribution` in `contracts/stats.py`; contribution is shadow−suppression, not class baseline |
| S5 | Benched skills cannot gather restoration evidence (not retrievable) | Bounded exploration/shadow slots for benched and newly approved versions | **Done** — `select_shadow_slots` in `src/fandea/memory/procedural/active_set.py`; `shadow_slots_per_task_class` in autonomy config; covered by `tests/e2e/test_m5_autonomy.py` |
| S6 | T3 "unreachable from run code" forbids importing the tool registry the runtime must use | Capability interfaces: read/use vs mutate; test forbidden writes, not blanket imports | **Done** — `ToolRuntime` invokes; `ToolRegistry.register` stays off `NodeContext`; import-boundary test guards T3 |
| S7 | Only skill/run schemas exist; M0 needs Policy, Criterion, NodeOutput, checkpoint, FailureSignal | Milestone-scoped contract backlog; add schemas before the milestone that consumes them | **Done** — Policy / NodeOutput / CheckpointRecord / ScopePromotion schemas generated; criteria remain embedded in `run.schema.json` |
| S8 | Research binaries and `.xls` duplicates live in `docs/` | Move to `research/`; xlsx+JSON only (was the entirety of the old plan) | **Done** — `research/*.xlsx` + `*.scored.json`; `.xls` removed |

---

## 2. Target shape after the refactor

Not a prettier folder tree — a clearer ownership model.

```text
Authority
├── docs/adr/                   decisions and their evidence status
├── docs/architecture.md        compatibility index for split architecture topics
├── docs/architecture/          intent, topology, and rationale by topic [R4 done]
├── docs/specifications.md      compatibility index for split normative contracts
├── docs/specifications/        normative MUSTs by topic [R4 done]
├── contracts/                  Pydantic models — normative structural source (ADR-0009) [done]
│   ├── profiles.py             approved-skill, candidate-skill, checkpointed-run, …
│   └── examples.py             canonical examples, code-generated, not hand-written JSON
├── schema/                     JSON Schema, generated from contracts/, never hand-edited [done]
├── docs/assumptions.md         research claims vs engineering gates [done]
├── docs/implementation-plan.md build order, revised against B6/B7 [done]
└── research/                   evidence dumps; never normative

Runtime (scaffolded empty until M0 fills it)
├── src/fandea/…                imports types from contracts/, does not redefine them
└── tests/{unit,property,contract,boundary,semantic}/
```

Document roles, fixed:

| Artifact | May contain | Must not contain |
| --- | --- | --- |
| ADR | A decision, alternatives, evidence status | Operational defaults that belong in policy |
| Architecture | Why and how pieces fit | `MUST` rules that duplicate specs |
| Specifications | Normative contracts | Narrative motivation already in architecture |
| Schema / profiles | Structure + checkable semantic invariants | Prose explanations |
| Assumptions register | Empirical claims and their verification state | Pass/fail gates for milestones |
| Implementation plan | Sequencing and done-whens that are engineering-checkable | "Reproduce paper result X" as a merge requirement |
| Research/ | Spreadsheets, extracted bibliographies | Anything a runtime imports |

---

## 3. Workstreams

### R0 — Hygiene (keep; demote)

Move research artifacts out of `docs/` into `research/`. Delete every `.xls`. Export
`scored.json` beside the workbook. Update links.

This is a small, mechanical PR (move files, delete `.xls`, export `scored.json`, fix links) —
not an architectural change. It does not unblock M0 by itself. Do it first only because every
later docs PR is noisier while binaries sit in the same tree.

### R1 — Resolve the seven blockers in the design docs — done

Landed as **one PR per blocker's worth of change**, not seven separate PRs and not one PR
with seven commits: B3+B4 (routing) and B1+B5 (data model / contracts-as-code) touch the same
`contracts/graph.py` and `RunState` surface and were genuinely one coherent change each; B2
and B6/B7 are independent and could have shipped separately. If this recurs, default to one
PR per blocker and only combine two blockers when a single test file would otherwise have to
import both halves to be meaningful — state that reason in the PR body, don't combine
silently. Every blocker got its own commit and its own contract test regardless of PR
grouping. Each PR was based on `main` directly (R5's stacked-PR ban), which is why this could
land without repeating the graph-execution branch's fate.

| Commit | Edits | ADR touchpoint | Files touched | Proven by (R3 check) | Acceptance |
| --- | --- | --- | --- | --- | --- |
| B1 | Split SkillVersion / Status / Stats | New: [ADR-0007](adr/0007-skill-identity-status-and-stats-split.md) | `contracts/skill.py`, `status.py`, `stats.py`; `schema/skill_version.schema.json` + 2 more; specs §1–§2; architecture §5.4 §7.1 §9; implementation-plan repo layout | `test_semantic_profiles.py` (approved-skill profile), `test_structural_validity.py` | No mutable field remains on the immutable version document; example updated |
| B2 | TaskCriterion vs SkillCertificationCriterion | Amend: [ADR-0003](adr/0003-criteria-preregistration.md) | `contracts/criteria.py`; specs §15.1 §15.4; architecture §11.1 | `test_criteria_timeline.py` | Scratch→candidate path states when certification criteria are authored and how they get preregistered relative to certification runs |
| B3 | Conditional join; real `MergeAudit` predicate | New: [ADR-0008](adr/0008-optional-join-and-failure-signals.md) | `contracts/graph.py`, `branch.py`; specs §4 §4.1; architecture §5.1; `README.md` diagram (no change needed — see fix above) | `test_route_completeness.py` | A single-branch run has a fully specified path to distill in M0 |
| B4 | FailureSignal + error edges; split quarantine | Same: [ADR-0008](adr/0008-optional-join-and-failure-signals.md) | `contracts/failure.py`; specs §4 §16 §21; architecture §5.1 | `test_route_completeness.py` | Every failure class in §16 has a legal producer; review rejection ≠ skill quarantine |
| B5 | Ownership rule; semantic profiles; contracts as code | New: [ADR-0009](adr/0009-contracts-as-code.md) | all of `contracts/`; `scripts/generate_schemas.py`, `export_examples.py`; specs (throughout); implementation-plan (repo layout, CI invariants) | `test_examples.py`, `test_schema_generation.py`, `test_structural_validity.py` | The canonical example passes `approved-skill`/`candidate-skill`, not merely parses; regenerating schema from contracts is a CI-checked no-op |
| B6 | Rewrite M0–M3 done-whens; pull forward mechanisms | — (prose fix, no ADR) | implementation-plan M0 M1 M3 | `scripts/check_milestone_deps.py` | No M0–M3 done-when cites a mechanism whose first landing is M4+ |
| B7 | `docs/assumptions.md`; split engineering gate from research outcome | — (prose fix, no ADR) | implementation-plan M4 M5 M9; new `docs/assumptions.md`; `references.md` §8 → pointer | `scripts/check_assumptions_hygiene.py` | A harness that correctly reports null lift can pass M4 |

**Order used:** B3 and B4 first (graph is unrunnable without them), then B1 and B5 (data
model — the same PR, since `contracts/graph.py`'s route table and `RunState`'s field types
are one surface), then B2 (criteria timeline, which only became statable once B1's
`SkillCertificationCriterion` had somewhere to live), then B6 (milestones against the
repaired contracts), then B7 (gates).

**B6/B7 are prose-sequencing fixes**, not data-model fixes. They are guarded by the Milestone
dependency and Assumptions hygiene checks in R3 below.

### R2 — Skeleton and generated contracts — done

- ~~`pyproject.toml`~~ — done; covers `contracts/` and `src/fandea/`.
- ~~Pydantic models as the working hand; JSON Schema emitted or checked in CI.~~ — done:
  `contracts/*.py` are the models; `scripts/generate_schemas.py --check` and
  `scripts/export_examples.py --check` run as CI steps in `.github/workflows/ci.yml`.
- ~~Semantic profile validators as first-class Python, not prose.~~ — done: `contracts/profiles.py`.
- Import-boundary / capability tests per S6 (use interfaces, not "cannot import registry") —
  **done** with the `src/fandea/` skeleton (see S6 in §1).

**Runtime types import from `contracts/`.** Do not hand-write competing `RunState`, routing, or
skill records in `src/fandea/`. B6/B7 (milestone prose, research gates) never shaped a data model.

### R3 — Contract CI that would have caught this — partially done

| Check | Fails when | Status |
| --- | --- | --- |
| Structural schema validity | Schema itself is invalid | Done — `test_structural_validity.py` |
| Lifecycle profiles | Canonical examples miss required semantic fields | Done — `test_examples.py`, `test_semantic_profiles.py` |
| Schema/example drift | Generated schema or exported example disagrees with `contracts/` | Done — `test_schema_generation.py` |
| Criteria timeline | `RunState.criteria` type-checks a `SkillCertificationCriterion` | Done — `test_criteria_timeline.py` |
| Route completeness | A strategy × outcome pair has no legal next node (route table in `contracts/graph.py`) | Done — `test_route_completeness.py` |
| Cross-refs | Dangling `§n` or cross-doc target | Done — `scripts/check_cross_refs.py` |
| Milestone dependency | A done-when names a symbol whose `introduced_in` milestone is later | Done — `scripts/check_milestone_deps.py` + `contracts/introduced_in.py` |
| Assumptions hygiene | A milestone done-when references an `assumptions.md` claim marked unverified as if it were a pass/fail gate | Done — `scripts/check_assumptions_hygiene.py` |

The five "Done" checks run as `pytest tests/contracts/` inside
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), alongside `ruff` and
`mypy` on `contracts/`, on every push to `main` and every PR touching `contracts/`, `scripts/`,
`schema/`, `skills/`, or `tests/contracts/`. They would have blocked B1–B5 from regressing;
they historically said nothing about B6/B7; assumptions-hygiene and milestone-dependency
CI now cover those. All eight R3 checks are enforced.

### R4 — Split the long docs

Only after R1. Splitting contradictory prose into more files freezes the contradictions in
a prettier tree. Cut along existing headings once the blockers are resolved; keep
redirect/index stubs for one milestone.

**Done.** `architecture.md` and `specifications.md` now provide compatibility indexes, with
coherent topic files under `architecture/` and `specifications/`. R3 cross-reference CI checks
that each compatibility index enumerates its required topic files.

### R5 — Branch hygiene

Delete merged agent branches. Ban stacked PRs against bases not already on `main`. The
last cycle lost graph-execution work on `main` for exactly that reason.

---

## 4. Sequencing

```text
R0  hygiene                         // done — research/ holds survey binaries
R1  B3 → B4 → B1 → B5 → B2 → B6 → B7   // done — see Resolution status
R2  skeleton + generated contracts  // done
R3  contract CI                     // done (8/8 checks)
R4  split docs                      // done
R5  branch cleanup                  // done — only main (+ active agent branches) remain
```

M0–M9 engineering done-whens are on `main`. Secondary debt S1–S8 and R0–R5 are done. Remaining
work is research outcomes in `assumptions.md` (needs real traffic).

---

## 5. What this plan is not

- Not a rewrite of the architecture's thesis. Graph-with-loops, plural memory, bounded
  library, verifier isolation, Blind Curator contribution rule — all stay.
- Not "implement M0 under a different name." Filling `classify_failure` is M0; defining
  what may legally enter it is R1.
- Not a docs site, not a literature database, not a re-score of the preprint survey.

---

## 6. Immediate next actions

R0–R5, S1–S8, and M0–M9 are done. Remaining work:

1. ~~Wire contracts CI + the three R3 hygiene scripts.~~ — done in `.github/workflows/ci.yml`.
2. ~~Land R0 (move research binaries out of `docs/`).~~ — done under `research/`.
3. ~~Secondary debt S1, S2, S4, S5.~~ — done; see §1 Status column for file pointers.
4. ~~Delete stale merged agent branches (R5).~~ — done; remote retains `main` only besides active work.
5. Research outcomes in [`assumptions.md`](assumptions.md) stay under evaluation until real
   traffic yields intervals.
