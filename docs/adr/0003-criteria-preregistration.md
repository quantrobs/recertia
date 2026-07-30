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
