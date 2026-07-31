# ADR-0007: Split skill identity from skill status and skill stats

- **Status:** accepted
- **Supersedes:** the single-document `SkillVersion` shape implied by `schema/skill.schema.json`
  before this decision
- **Evidence base:** [`../refactor-plan.md`](../refactor-plan.md) B1

## Context

`specifications/core-entities.md` §1 states the load-bearing rule plainly: `SkillVersion` is "**Immutable
once written**." Rollback safety, reproducibility of any historical run, and the git-as-memory
model in `architecture/task-plane.md` §5.4 all depend on that sentence being literally true.

It was not. `schema/skill.schema.json` embedded `lifecycle`, `active`, `trust`, `contribution`,
`retirement`, and `certification` in the same JSON document as the immutable content —
`skill_id`, `steps`, `success_criteria`, `provenance`. Every one of those fields changes after
the version is written: a promotion advances `lifecycle`; every application updates `trust`;
every scheduled evaluation updates `contribution`; every bench/restore rewrites `retirement`;
every drift check rewrites `certification`.

An implementer following the prose literally could not write any of those updates without
either (a) rewriting an "immutable" document, silently breaking rollback and the content-address
identity the store relies on, or (b) inventing an un-specified side table — which is what every
implementer would in fact do, inconsistently, absent a decision.

## Decision

Split one conflated document into three, with three different mutability regimes and three
different governance tiers ([ADR-0005](0005-self-modification-boundary.md)):

| Record | Identity | Mutability | Tier | Holds |
| --- | --- | --- | --- | --- |
| `SkillVersion` | `(skill_id, version)`, content-addressed | Immutable once written | T1 (write path is promotion-gated; the document itself never changes) | `skill_id`, `version`, `supersedes`, `title`, `intent`, `task_class`, `tags`, `parameters`, `preconditions`, `steps`, `uses`, `certification_criteria` (§ADR-0007 companion, see amended ADR-0003), `failure_modes`, `provenance`, `hygiene` |
| `SkillStatus` | `(skill_id, version)`, append-only event log projected to current state | Append-only; the projection is recomputed, never edited | T1 for lifecycle transitions (promotion-gated); T0 for the `active` flag (recomputed by the Curator, derived) | `lifecycle`, `active`, `certification` (model/tool fingerprint last validated against — this drifts, so it lives here, not on the version), `retirement` |
| `SkillStats` | `(skill_id, version)`, one row, rebuilt from the run store | Derived, rebuildable | T0 | `trust`, `contribution` |

Two fields that a first read might expect to stay on `SkillVersion` deliberately do not:

- **`hygiene.secret_scan` stays on `SkillVersion`.** It is a one-time gate evaluated once, at
  store time, before the immutable document is ever written — it never changes afterward, so it
  is data about the version's content, not a status.
- **`certification` moves to `SkillStatus`, not `SkillStats`.** It records what the version was
  *validated against* (model, tool fingerprints), and a model upgrade or tool change can mark a
  version `needs_recert` without any new evidence being collected — that is a lifecycle-relevant
  fact, not a derived statistic, and losing it would make `needs_recert` unrecoverable from
  `SkillStatus` alone.

`active` is derived from the active-set computation
(`specifications/library-authoring-and-concurrency.md` §24.1), never
authored directly on any record — it lives on `SkillStatus` because the active set is a
current-membership fact, not raw telemetry, but it is fully recomputed on every Curator pass and
carries no independent evidentiary weight of its own.

## Rationale

Three different write cadences were being forced into one document with one mutability rule.
`SkillVersion` changes once, at authoring or evolution. `SkillStatus` changes on a governed
schedule (promotions, recertifications) and must be auditable — an append-only log is what
makes "why is this version `needs_recert`" answerable without trusting a single mutable field.
`SkillStats` changes on every application and must be cheap to recompute — treating it as
derived (T0) means a corrupted or lost stats row is a rebuild, not a data-loss incident.

Splitting by mutability regime rather than by subject matter is also what keeps the retrieval
path honest: `retrieve` reads `SkillVersion` (content) joined with the current `SkillStatus`
projection (is it `approved` and `active`) and `SkillStats` (for ranking) — three cache-friendly
reads instead of one document that would need to be re-fetched on every trust update just to
read steps that never changed.

## Consequences

- The canonical store path becomes `skills/<skill_id>/v<N>/version.json` (immutable, in git,
  reviewed by pull request) plus a `SkillStatus` event log and a `SkillStats` row that are
  **not** git-reviewed artifacts — they are runtime state, rebuildable from the run store and
  the status event log respectively. `implementation-plan.md`'s repository layout is updated to
  reflect this (§ "Repository layout").
- `architecture/library-lifecycle.md` §7.1's lifecycle diagram is a diagram of `SkillStatus`
  transitions, not of the version document; the diagram itself does not need to change, but its
  caption does.
- [ADR-0006](0006-bounded-library-and-retirement.md)'s retirement mechanism now mutates
  `SkillStatus` (`lifecycle`, `retirement`) and reads `SkillStats` (`contribution`) — it was
  already describing this split informally ("retained in full with history"); this ADR makes it
  the literal storage model.
- The immutability CI invariant in `implementation-plan.md` ("no write to an existing
  `SkillVersion`") is now checkable by construction: `SkillVersion` is a frozen model, and there
  is no code path that could even attempt the write the invariant used to guard against by
  convention alone.
- `contracts/status.py` and `contracts/stats.py` (this refactor) are the executable form of this
  decision; `scripts/generate_schemas.py` emits `schema/skill_version.schema.json`,
  `schema/skill_status.schema.json`, and `schema/skill_stats.schema.json` from them, replacing
  `schema/skill.schema.json`.
