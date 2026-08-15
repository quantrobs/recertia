# ADR-0009: Contracts as code — Pydantic models are the normative structural source

- **Status:** accepted
- **Evidence base:** B5

## Context

The refactor plan's B5 finding was the sharpest indictment in the diagnosis: "schemas win on
conflict" had already been stated as policy, but the canonical skill example in
`specifications/core-entities.md` §2 *validated* against `schema/skill.schema.json` while missing several
fields the prose called mandatory (`preregistered`, `sensitivity_proof`, `certification`,
`hygiene.secret_scan`, `provenance.curation`). The run schema independently omitted `criteria`
and `advisory_criteria` from `RunState` and required only four top-level fields, so an
empty-budget run validated cleanly. A contract-CI job running a JSON Schema validator against
these documents would stay green while accepting states the prose explicitly forbids.

The root cause is not that the schemas were wrong in these particular fields — it is that prose
and schema are two independent, hand-maintained artifacts with no mechanism forcing them to
agree, and the drift is invisible until someone reads both closely, which nothing was requiring
anyone to do.

## Decision

Pydantic v2 models under `contracts/` are the single normative source for structure. Nothing
else hand-maintains a competing structural definition:

1. **`contracts/*.py` defines every entity** named in the specifications topic files (`SkillVersion`,
   `SkillStatus`, `SkillStats`, `TaskCriterion`, `SkillCertificationCriterion`, `RunState`,
   `Branch`, `FailureSignal`, `FailureVerdict`, `MergeAudit`, ...), using Pydantic's own
   validators (`Field` constraints, `model_validator`) to encode every MUST that a structural
   schema can express: required fields, enums, cross-field constraints (`loop.max_iterations`
   required when `loop` is present; `input_bindings` referencing existing predecessor step ids
   and declared outputs; derived step DAGs with no free-floating `depends_on`).
2. **`schema/*.schema.json` is generated, never hand-edited.** `scripts/generate_schemas.py`
   calls `model_json_schema()` on each public contract model and writes the result. A CI check
   (`tests/contracts/test_schema_generation.py`) regenerates into a temp directory and diffs
   against the checked-in files; a diff fails CI. This makes "the schema matches the model"
   true by construction rather than by discipline.
3. **Semantic profiles are executable, not prose.** Rules a structural schema cannot express —
   "every required criterion has a valid sensitivity proof," "an approved skill has at least one
   non-`judge` required criterion," "a checkpointed run's criteria hash matches its locked
   criteria" — are Python functions in `contracts/profiles.py` returning a list of violations.
   `approved-skill`, `candidate-skill`, and `checkpointed-run` are the three profiles this
   refactor ships; more are added as new lifecycle gates are specified.
4. **Canonical examples are Python objects, not hand-written JSON.** `contracts/examples.py`
   constructs the canonical `bump-python-dep` skill (version, status, stats) as typed model
   instances. `scripts/export_examples.py` dumps them to `skills/bump-python-dep/v3/*.json` for
   the documents to reference and for humans to read; `tests/contracts/test_examples.py` asserts
   the canonical example passes the `approved-skill` profile, not merely that it parses. This is
   the fix for the specific B5 example that motivated the ADR: it is no longer possible for the
   canonical example to silently drift below the semantic bar, because the test that would catch
   it runs against the same object the documentation embeds.
5. **Prose still owns *why*; schema still owns *shape*; profiles own the semantic MUSTs in
between.** This ADR does not change the division of labour between the architecture and
specifications topic files (rationale vs. normative contract) — it changes what "normative contract"
   is made *of*.

## Rationale

A generated artifact cannot drift from its generator; only the generator can be wrong, and the
generator is now one file per entity instead of one prose paragraph plus one hand-written JSON
Schema block that happened to agree on the day it was written. Semantic profiles exist because
JSON Schema genuinely cannot express some of the MUSTs in this design (a required criterion's
sensitivity proof must have `rejected == true`; that is a cross-field, value-dependent
constraint outside JSON Schema's vocabulary without resorting to unreadable `if/then` chains) —
writing them as Python functions instead of straining JSON Schema to its limits is honest about
where the expressiveness boundary actually is.

This is also the concrete first slice of `archive/2026-Q3/implementation-plan.md`'s R2 workstream
("Pydantic models as the working hand; JSON Schema emitted or checked in CI"), pulled forward
because the B1–B5 blockers could not be verified as *actually* resolved by prose alone — the
only way to be sure the three-way split in ADR-0007, the criteria timeline in the amended
ADR-0003, and the routing fix in ADR-0008 are mutually consistent was to write them down as
types and let a type checker and a test suite find the seams.

## Consequences

- `contracts/` exists in the repository before `src/recertia/` is scaffolded. This is a deliberate,
  narrow exception to "no runtime code before M0": `contracts/` is specification tooling, not
  the graph engine, the solver, or any node implementation. `src/recertia/` continues to wait for
  M0, and when it arrives, `src/recertia/memory/procedural` (etc.) import from `contracts/` rather
  than redefining these types.
- `archive/2026-Q3/implementation-plan.md`'s repository layout gains a top-level `contracts/` directory ahead of
  `src/`; its R2 milestone task ("Pydantic models as the working hand") is now "wire
  `src/recertia/` to `contracts/`" rather than "write the models."
- Every future new mutable surface or entity is added by writing a Pydantic model first; a
  hand-written JSON Schema change with no corresponding model change is a review-blocking smell.
- `docs/archive/2026-Q3/refactor-plan.md`'s R3 "Structural schema validity" and "Lifecycle profiles" CI checks
  are now literally the test files this ADR describes, not future work.
