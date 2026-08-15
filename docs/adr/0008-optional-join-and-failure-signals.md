# ADR-0008: Optional join, explicit failure signals, and split terminals

- **Status:** accepted
- **Evidence base:** [`../refactor-plan.md`](../archive/2026-Q3/refactor-plan.md) B3, B4; corroborated by
  `README.md`'s simplified loop diagram, which never routed through a `join` node

## Context

Two routing contradictions made the graph unrunnable before fan-out exists (M0–M5, per
`archive/2026-Q3/implementation-plan.md`):

**B3 — universal join.** `architecture/task-plane.md` §5.1 draws `validate → join` unconditionally, for
every run, including the ordinary single-attempt case that M0–M5 exercise exclusively.
`specifications/graph-execution.md` §4 defines `join` only in terms of branches, portfolio selection, and
decomposition synthesis — concepts that do not exist until fan-out (M6). Worse, the routing
predicate tested `merge_audit.complete`, a field `MergeAudit` does not have; it has
`action ∈ {proceeded, flagged, failed}`. There was no specified route from a successful
single-attempt validation to `distill` anywhere in the documents.

`README.md`'s simplified loop diagram was, in this one respect, already correct: it draws
`V -->|pass| D` directly, with no `join` on the default path. The detailed diagrams and the
specs table were the ones wrong, not the simplification.

**B4 — `classify_failure` cannot legally fire for most failure classes.** Its stated
precondition was "some required criterion failed." But `environment`, `tool`, and `budget`
failures are defined (specs §16) as occurring *before or instead of* validation — there may be
no result vector at all. A `merge` gap need not produce a failed criterion either; it is a
structural fact about missing inputs. And `review → quarantine` fired with no `failure` set,
violating `quarantine`'s own stated precondition. Separately, "quarantine" as written conflated
three different acts — recording a failed run, rejecting a reviewed draft, and marking a stored
skill version harmful — under one node and one word.

## Decision

### Join is conditional, not universal

`join` exists only when `state.branches` is non-empty (i.e., `fan_out` ran). The default,
branch-free path is:

```text
validate → distill            : criteria pass
validate → classify_failure   : criteria fail, or a FailureSignal was raised
```

The fan-out path remains:

```text
validate → join               : branches is non-empty
join → distill                : merge complete AND selected/synthesised result passes required criteria
join → classify_failure       : otherwise
```

This is Option 1 from the refactor plan, chosen definitively rather than left open: it needs no
new concept (`ExecutionGroup` of size 1, the alternative considered, would have required every
M0–M5 node to reason about a fan-out abstraction that does not exist yet for their own sake).
`architecture/task-plane.md`'s detailed diagram and `specifications/graph-execution.md` §4
change; `README.md`'s diagram does not.

### Failures are signalled explicitly, not inferred from a result vector

A `FailureSignal` (source: `orchestrator | solver | validator | join`, detail, timestamp) is the
one precondition `classify_failure` requires: `state.failure_signal is not None`. It can be
raised:

- by the orchestrator or solver, before `validate` ever runs (environment setup failure, budget
  exhaustion mid-attempt) — routing `solve → classify_failure` directly;
- by `validate`, when a required criterion fails — replacing the old "some required criterion
  failed" precondition with an explicit signal `validate` constructs from exactly that fact, so
  the precondition is checkable without re-deriving it from the result vector every time;
- by `join`, on a merge gap or resource-claim deadlock
  (`specifications/library-authoring-and-concurrency.md` §26.4).

### Terminals are split by what they act on, and quarantine of a *version* leaves the task graph entirely

Three different things were called "quarantine":

1. **A run failed and budget or strategy is exhausted.** Fix: `classify_failure →
   record_dead_end`. Writes the episodic `dead_end` record; terminal is `unsolved`.
2. **A reviewer or policy rejects a freshly distilled draft.** Fix: `review → reject_draft`.
   The draft is not written; the evidence (what was tried, what was rejected and why) is
   retained for the Correction Miner (specs §20).
3. **An already-`approved` skill version is marked harmful** — two consecutive field failures,
   or a recertification rejection. This is **not** a task-plane decision at all: no single run
   has the aggregate evidence (two consecutive failures, or a recert comparison) to make this
   call. It is a `SkillStatus` transition made by the Recertifier or Curator
   (`specifications/evaluation-improvement-and-governance.md` §20), reading across runs. Removing it from the task-plane graph
   entirely — rather than adding a third graph node, as the refactor plan first sketched — is a
   sharper fix: it stops a single run's `classify_failure` from ever being able to reach into
   governance state it has no standing to change, which is exactly the kind of authority
   `architecture/risk-and-governance.md` §14 exists to bound.

The task-plane graph therefore has two failure terminals, not three, and neither can quarantine
a stored skill version:

```text
classify_failure → evolve            : budget remains, progress observed, class not in {criteria, budget}
classify_failure → record_dead_end   : otherwise
distill → review                     : reusable
review → store                       : approved
review → reject_draft                : rejected
```

## Rationale

Both fixes remove a node from having to satisfy a contract that presupposes a mechanism not yet
built (fan-out, or cross-run aggregate evidence) while still leaving that mechanism's eventual
hook in place: `join` activates the moment `fan_out` starts populating `branches`, with no
further change to its own contract; `FailureSignal` is already the right shape for the
Recertifier to also raise when it independently decides a version needs `quarantine_version` —
it simply never routes through the task-plane graph to do so.

Removing the third terminal rather than adding it is the meta-lesson of this ADR: a graph fix is
better than a schema fix when the honest answer is that a decision does not belong in the graph
being fixed.

## Consequences

- `contracts/graph.py`'s route table encodes exactly the edges above and is exhaustively tested
  (`tests/contracts/test_route_completeness.py`): every `FailureClass` has at least one producing
  edge, and every node has at least one legal outgoing route for every reachable state.
- `specifications/graph-execution.md` §4/§4.1, `architecture/task-plane.md` §5.1's diagram and
  node table, and `archive/2026-Q3/implementation-plan.md`'s M0 node list are updated to match (fourteen nodes become fifteen:
  `quarantine` is removed, `record_dead_end` and `reject_draft` are added; `quarantine_version`
  is documented under the Recertifier/Curator in specs §20, not in the node table).
- `docs/archive/2026-Q3/refactor-plan.md` marks B3 and B4 resolved with a link back here.
