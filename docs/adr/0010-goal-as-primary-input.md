# ADR-0010: Goal as primary task input (Variant B)

- **Status:** accepted
- **Date:** 2026-07-31

## Context

The public entry point for a run was a free-text `request` string. Criteria were either
supplied optionally or proposed by a critic from that prose, then locked. Internally the
system already treated locked `TaskCriterion[]` as the success contract (ADR-0003). The
input model lagged that reality: callers could (and golden fixtures did) ship pure prose and
rely on inference.

Literature on self-improving agents (Ratchet, SkillsBench, Blind Curator) shows that weak or
post-hoc success conditions undermine measurement, contribution, and retirement. Making the
machine-checkable contract primary strengthens those surfaces.

## Decision

1. Introduce a structured `Goal` type (`contracts/goal.py`) with `DesiredState` and
   `Constraint` lists. A Goal MUST contain ≥1 required non-judge DesiredState.
2. `Goal` compiles deterministically to `list[TaskCriterion]` via `compile_goal`.
3. `Task.goal` is the preferred primary input; `Task.request` becomes optional context.
4. At `intake`, Goal is compiled and locked; the critic only authors missing sensitivity
   proofs (refine), not the success conditions themselves, when a Goal is present.
5. Legacy pure-`request` path remains for compatibility; new clients SHOULD supply a Goal.
6. Strategy hints move to `Goal.strategy_hint`; plan prefers that over request-string prefixes.

## Consequences

- Callers get a clearer, checkable contract; measurement integrity improves.
- Authoring cost rises slightly; mitigated by task-class templates and critic refine.
- Schema, API, CLI, and golden fixtures gain a dual path (goal preferred).
- No change to graph topology, memory planes, skill certification timeline, or contribution
  math — those already consume locked criteria.

## Alternatives considered

- **Criteria-only (Variant A):** simpler, less expressive for constraints and future
  decomposition ownership. Rejected in favour of Goal for clarity and extensibility.
- **Pure PDDL / classical planning:** too rigid for open repo-chore and research domains.
- **Keep prompt-first:** continues the mismatch between public API and internal contract.
