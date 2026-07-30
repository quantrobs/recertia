# Repository refactor plan

The previous version of this plan moved files. That is necessary and is still R0 below.
It is not the problem.

The problem is that the design, as written, **cannot be implemented without inventing
answers the docs pretend to have already given**. Several load-bearing contracts are
internally contradictory; the milestone order asks M0–M3 to satisfy MUSTs that only exist
in M4–M6; and "the schema is the source of truth" is false today — the canonical skill
example validates against the schema while missing half the fields the prose requires for
an `approved` skill.

This plan is the work that has to happen **before M0 writes a line of runtime code**. It
is a design refactor with a small amount of repo hygiene attached, not the reverse.

Verified against `main` at the time of writing. Claims below cite concrete fields and
routing predicates, not vibes.

---

## 0. Diagnosis: seven blockers

### B1. `SkillVersion` is immutable and continuously rewritten

`specifications.md` §1: `SkillVersion` is "**Immutable once written**." M1 refuses any
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

**Fix (pick one, write it down, delete the other):**

1. **Preferred for M0:** ordinary runs route `validate → distill | classify_failure`.
   `join` exists only when `branches` is non-empty.
2. Or: every attempt is an `ExecutionGroup` of size 1 from M0, and `join` is the universal
   reducer with trivial singleton behaviour.

Do not leave a node on the critical path whose contract assumes M6.

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

| ID | Debt | Sharper fix than "document it" |
| --- | --- | --- |
| S1 | Step DAG has `depends_on` but no declared outputs / bindings; fake-edge test is unenforceable | Derive edges from typed `input_bindings` → `step.output`; drop free-floating `depends_on` as authoring input |
| S2 | `retrieve` "must not execute" but preconditions include `command_succeeds` | Registered read-only probes with budget and evidence, not arbitrary commands |
| S3 | `Branch` has no status, spend, transcript, snapshot; schema omits `budget` | `BranchState` + `BudgetLease` against a parent ledger; reserve join overhead |
| S4 | `skill_contribution` subtracts a class baseline from a non-randomly selected skill | Three quantities, stored once: predictive trust, class-level retrieval effect (ablation), per-skill effect (shadow/suppression) |
| S5 | Benched skills cannot gather restoration evidence (not retrievable) | Bounded exploration/shadow slots for benched and newly approved versions |
| S6 | T3 "unreachable from run code" forbids importing the tool registry the runtime must use | Capability interfaces: read/use vs mutate; test forbidden writes, not blanket imports |
| S7 | Only skill/run schemas exist; M0 needs Policy, Criterion, NodeOutput, checkpoint, FailureSignal | Milestone-scoped contract backlog; add schemas before the milestone that consumes them |
| S8 | Research binaries and `.xls` duplicates live in `docs/` | Move to `research/`; xlsx+JSON only (was the entirety of the old plan) |

---

## 2. Target shape after the refactor

Not a prettier folder tree — a clearer ownership model.

```text
Authority
├── docs/adr/                   decisions and their evidence status
├── docs/architecture/          intent, topology, rationale (split in R4)
├── docs/specifications/        normative MUSTs; owns semantics
├── schema/                     structural contracts; generated or checked against Pydantic
│   └── profiles/               approved-skill, candidate-skill, checkpointed-run, …
├── docs/assumptions.md         research claims vs engineering gates (new)
├── docs/implementation-plan.md build order, revised against B6
└── research/                   evidence dumps; never normative

Runtime (scaffolded empty until M0 fills it)
├── src/fandea/…
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

This is a half-day PR. It does not unblock M0 by itself. Do it first only because every
later docs PR is noisier while binaries sit in the same tree.

### R1 — Resolve the seven blockers in the design docs

One PR per blocker, or one PR with seven commits — but each blocker gets its own commit
message and its own contract tests.

| Commit | Edits | Acceptance |
| --- | --- | --- |
| B1 | Split SkillVersion / Status / Stats in specs §1–§2, schema, ADR-0006 touchpoints | No mutable field remains on the immutable version document; example updated |
| B2 | Introduce TaskCriterion vs SkillCertificationCriterion; rewrite §15 and distill path | Scratch→candidate path states when certification criteria are authored and how they get preregistered relative to certification runs |
| B3 | Fix validate routing; define singleton join or remove join from the default path; replace `merge_audit.complete` with a real predicate on `action` | A single-branch run has a fully specified path to distill in M0 |
| B4 | FailureSignal + error edges; split quarantine meanings | Every failure class in §16 has a legal producer; review rejection ≠ skill quarantine |
| B5 | Ownership rule; semantic profiles; repair run schema (`criteria`, branch budget, …); make the canonical example pass `approved-skill` | `pytest tests/semantic` fails if the example regresses; structural-only CI is not enough |
| B6 | Rewrite M0–M3 done-whens and pull forward seed approval, sensitivity execution, active assignment, golden runner stub, checkpoint idempotency | No M0–M3 done-when cites a mechanism whose first landing is M4+ |
| B7 | Add `docs/assumptions.md`; demote empirical thresholds to T2 defaults; rewrite M4/M5 done-whens to accept "not established" | A harness that correctly reports null lift can pass M4 |

**Order inside R1:** B3 and B4 first (graph is unrunnable without them), then B1 and B5
(data model), then B2 (criteria timeline), then B6 (milestones against the repaired
contracts), then B7 (gates).

### R2 — Skeleton and generated contracts

- `pyproject.toml`, empty `src/fandea/` packages per the implementation plan.
- Pydantic models as the working hand; JSON Schema emitted or checked in CI.
- Semantic profile validators as first-class Python, not prose.
- Import-boundary / capability tests per S6 (use interfaces, not "cannot import registry").

### R3 — Contract CI that would have caught this

| Check | Fails when |
| --- | --- |
| Structural schema validity | Schema itself is invalid |
| Lifecycle profiles | Canonical examples miss required semantic fields |
| Cross-refs | Dangling `§n` or cross-doc target |
| Route completeness | A strategy × outcome pair has no legal next node (machine-readable route table extracted from specs §4.1) |
| Milestone dependency | A done-when names a symbol whose `introduced_in` milestone is later |
| Assumptions hygiene | A milestone done-when references an assumptions-register claim marked unverified as if it were a pass/fail gate |

The route-completeness and milestone-dependency checks are the ones that would have blocked
B3 and B6 from landing. Build them before the next design accretion.

### R4 — Split the long docs

Only after R1. Splitting contradictory prose into more files freezes the contradictions in
a prettier tree. Cut along existing headings once the blockers are resolved; keep
redirect stubs for one milestone.

### R5 — Branch hygiene

Delete merged agent branches. Ban stacked PRs against bases not already on `main`. The
last cycle lost graph-execution work on `main` for exactly that reason.

---

## 4. Sequencing

```text
R0  hygiene                         // parallel, cheap
R1  B3 → B4 → B1 → B5 → B2 → B6 → B7   // the actual refactor
R2  skeleton + generated contracts  // after B1/B5 shape is stable
R3  contract CI                     // after R2; encodes R1 invariants
R4  split docs                      // after R1, optionally after first M0 spike
R5  branch cleanup                  // anytime
```

M0 starts after **R1 + R2 + R3**. Not after R0. Not after R4.

---

## 5. What this plan is not

- Not a rewrite of the architecture's thesis. Graph-with-loops, plural memory, bounded
  library, verifier isolation, Blind Curator contribution rule — all stay.
- Not "implement M0 under a different name." Filling `classify_failure` is M0; defining
  what may legally enter it is R1.
- Not a docs site, not a literature database, not a re-score of the preprint survey.

---

## 6. Immediate next actions

1. Open the R1.B3 PR: repair `validate` routing and the `merge_audit.complete` phantom
   predicate. Smallest change that makes a single-attempt run expressible.
2. Open R1.B4 behind it: `FailureSignal` and the quarantine split.
3. Land R0 in parallel so research binaries stop hitchhiking on design PRs.
4. Do not scaffold `src/` until B1's SkillVersion split is written — otherwise the first
   Pydantic models will encode the contradiction.
