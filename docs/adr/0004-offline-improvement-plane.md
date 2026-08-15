# ADR-0004: A separate offline improvement plane

- **Status:** accepted

## Context

The first draft learned only during user-facing runs: solve, distill, review, store. Anything
that a run cannot do while a user waits therefore could not happen at all. That excluded four
capabilities that a system claiming to improve itself needs:

- **Bootstrap.** An empty library makes the system slower and worse than a plain agent exactly
  when it is first evaluated, even though the repository's history is full of solved tasks.
- **Reorganisation.** Retrieval precision decays as a library grows with duplicates,
  overlapping skills, and over-specific entries. No run has the time or the cross-library view
  to fix that, and decaying retrieval attacks the system's central thesis.
- **Practice.** Learning only from traffic means never improving at what traffic does not
  cover, including the classes the system is measurably worst at.
- **Rot detection.** Skills break without being touched when tools, APIs, or model versions
  change. A skill that is never retrieved is never discovered to be broken.

## Decision

Add a third plane of scheduled offline jobs alongside the online task plane and the durable
memory plane: **Miner** (bootstrap from git history, PRs, CI config, runbooks), **Curator**
(compaction, abstraction, deprecation, precondition tightening), **Practice** (curriculum
targeting the competence frontier), **Recertifier** (scheduled and triggered drift checks), and
**Correction miner** (mine reviewer edits into distiller guidance proposals).

No job writes `approved` state directly. Every job produces proposals that pass through the
same validation, golden-set regression gate, and review path as a run's output.

## Rationale

These jobs need properties an online run cannot have: a whole-library view, tolerance for long
runtimes, freedom to fail without affecting a user, and the ability to run when there is no
task. Making them jobs rather than run-time behaviour also keeps the online graph small and
keeps user-facing latency unaffected by library maintenance.

Routing proposals through the normal review path is what keeps this from becoming an
autonomous background rewriter of durable state: the jobs get to *propose* anything and
*promote* nothing.

## Consequences

- A scheduler and job runner are needed, plus per-job budgets so practice cannot consume the
  spend meant for real work.
- Practice runs must be marked and excluded from user-facing metrics, or the metrics become
  self-referential.
- The Curator can propose sweeping changes; the golden-set regression gate is therefore a hard
  prerequisite, and Curator work cannot land before the eval harness exists.
- Mined candidates carry weaker provenance than distilled ones — they were not executed under
  validation when mined — so they must be validated before promotion, not trusted because they
  came from merged history.
- This is where "self-improving" mostly lives. It is also the largest new surface area, and the
  reason the build order defers it until measurement is trustworthy.
