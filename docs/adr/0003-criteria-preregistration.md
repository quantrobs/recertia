# ADR-0003: Pre-registered criteria with sensitivity proofs

- **Status:** accepted

## Context

In the first draft, `distill` proposed a skill's `success_criteria` from the transcript of the
run that had just succeeded. The intended safeguard was that criteria must be
machine-checkable and that a human reviews them.

That safeguard is weaker than it looks. Criteria authored from a successful transcript are
selected, however unintentionally, to be criteria that the transcript satisfies. The model is
grading work against a rubric written after seeing the work. Nothing in the schema prevents a
criterion suite that is trivially satisfiable — `pytest -q` on a suite with no relevant tests
exits 0 — and a reviewer skimming a plausible skill will not reliably catch it.

This is the classic Goodhart failure, and in a self-improving system it is worse than usual:
weak criteria do not merely mismeasure one run, they get stored, promoted, retrieved, and used
to certify future work.

## Decision

Two structural changes:

1. **Pre-registration.** Required success criteria are locked at `intake`, before `solve`
   runs, and their hash is recorded in the run manifest. When the caller supplies none, a
   separate critic pass proposes them from the task intent, in a different context from the
   solver. Criteria may be added mid-run only as advisory (`weight < 1.0`); required criteria
   are immutable once locked.

2. **Sensitivity proofs.** Every criterion must demonstrate that it *rejects* a known-bad
   artifact — the pre-solve workspace, a mutated artifact, or a recorded prior failure — before
   it counts toward promotion. Criteria without a proof are advisory only.

Additionally, the `criteria` failure class escalates to a human and never permits the system
to relax criteria as a repair move.

## Rationale

Pre-registration removes the incentive path: the target exists before the work, so it cannot
be fitted to it. Sensitivity proofs remove the residual case where an honestly pre-registered
criterion is simply vacuous — mutation testing applied to validators.

Together they replace "a human should notice bad criteria" with two mechanical checks, which
is what the review gate needs in order to relax over time (shadow promotion) without the
system's scorecard degrading.

## Consequences

- `intake` needs criteria synthesis before solving, so a critic pass sits on the critical path
  for tasks with no declared criteria.
- Every criterion needs a known-bad fixture. For `command` criteria the pre-solve workspace is
  usually sufficient; `judge` criteria need explicit negative examples, which is a further
  reason they cannot gate promotion alone.
- Some legitimate criteria can only be known after solving. Handled by admitting them as
  advisory, surfaced to review, and eligible to become required in the *next* version.
- Criteria drift becomes visible: since criteria are versioned with the skill, weakening them
  is a diff a reviewer sees, and the regression gate re-runs the prior version's criteria.

## Amendment: two criteria timelines (2026-07-30)

This ADR was silent on one timeline collision, flagged in
[`archive/2026-Q3/refactor-plan.md`](../archive/2026-Q3/refactor-plan.md) B2: `intake` locks required criteria *before*
`retrieve` and `plan` run, so no skill has been chosen yet — but the original text listed
"skill-inherited (when a skill is applied)" as a lock source, which is temporally impossible.
Separately, a skill's own certification criteria are authored at `distill` time, *after* the run
that produced them succeeded, which looks like exactly the post-hoc fitting this ADR exists to
prevent, unless the timeline for *those* criteria is stated separately from the run's timeline.

**Clarifying decision: these are two different measurement questions, with two different
criteria types and two different timelines, and they never merge.**

1. **`TaskCriterion`** answers "did this run solve what the caller asked for?" It is locked at
   `intake`, from the caller, a task-class default template, or a critic pass — **never** from
   a skill, because no skill is chosen yet. This is unchanged from the original decision and
   remains genuinely pre-registered relative to solving.
2. **`SkillCertificationCriterion`** answers "does this skill version reliably do what it
   claims?" It is authored once, at `distill` time, from the transcript that produced the draft
   — and is therefore *not* pre-registered relative to that first transcript, by construction,
   the same way any transcript-derived rubric is post-hoc. "Preregistered" for this type means
   registered **before the certification runs that validate it** — the shadow trials and
   scheduled recertifications in specs §8/§20 — not before the original success. A version
   cannot reach `candidate` on the strength of the transcript it was born from; it reaches
   `candidate` only after its certification criteria are re-run, cold, on independent fixtures.

**The load-bearing consequence:** a run's locked `TaskCriterion` set is **never** modified,
extended, or replaced by which skill `plan` happens to choose. A skill's certification criteria
may additionally be evaluated against the same run's artifact — this is a free observation,
since the artifact already exists — but that observation is advisory telemetry feeding
`SkillStats`/`needs_recert` (specs §20), and it never gates `join`, `distill`, or the caller's
result. This closes the reopened gaming path the original text's "skill-inherited" language
would have created: if certification criteria could enter a run's required set, a caller could
be told a task "solved" against a bar the caller never asked for and never saw, chosen after the
fact by which skill got retrieved.

See [ADR-0009](0009-contracts-as-code.md) for the executable form: `contracts/criteria.py`
defines `TaskCriterion` and `SkillCertificationCriterion` as distinct types, and
`contracts/run.py`'s `RunState.criteria` is typed `list[TaskCriterion]` — a
`SkillCertificationCriterion` cannot type-check into a run's required set at all.
