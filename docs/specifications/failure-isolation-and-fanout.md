# Recertia Specifications: 16. Failure taxonomy

## 16. Failure taxonomy

`classify_failure`'s only precondition is `state.failure_signal is not None` (§4, ADR-0008), not
"some required criterion failed" — most classes below have no result vector to have failed.
`FailureSignal` is raised by the orchestrator, solver, validator, or join; `classify_failure`
reads the signal plus evidence (affordance matches, criterion ids, merge audits) to assign a
class.

```python
FailureClass = Literal[
    "environment", "tool", "retrieval", "plan", "execution", "criteria", "budget", "merge"
]

class FailureSignal(BaseModel):
    source: Literal["orchestrator", "solver", "validator", "join"]
    detail: str
    at: datetime

class FailureVerdict(BaseModel):
    failure_class: FailureClass
    evidence: list[str]              # criterion ids, tool errors, affordance matches
    implicated_skill: dict | None
    counts_against_trust: bool       # False for environment, tool, budget, merge
    escalate_to_human: bool          # True for criteria
```

| Class | Detection | `evolve` move | Trust impact |
| --- | --- | --- | --- |
| `environment` | Failure before first productive tool call, or setup criterion failed | Repair environment, keep strategy | None |
| `tool` | Error signature matches affordance record, or flake rate above threshold | Retry with backoff, or substitute tool | None |
| `retrieval` | Applied skill's preconditions passed but its steps were inapplicable | Drop candidate, re-retrieve, propose tighter preconditions | Yes, on the skill |
| `plan` | Required criteria failed with no partial progress | Switch strategy, escalate model tier | Yes, if a skill was applied |
| `execution` | Partial progress with specific criterion failures | Patch artifacts using criterion output | Yes |
| `criteria` | Criteria unsatisfiable, mutually contradictory, or sensitivity proof invalid | **None** — routes to `record_dead_end`, never `evolve` | None |
| `budget` | Any budget exhausted | **None** — routes to `record_dead_end`, never `evolve` | None |
| `merge` | A merge audit reported missing inputs, or a resource claim deadlocked (§26.2, §26.4) | Re-dispatch only the missing branches or steps once, from their retained snapshot; a deadlock re-runs the cycle serially | None |

`merge` exists as its own class because the repair is narrow — rerun the piece that never
arrived — and because charging trust for a branch that died in the executor would let
infrastructure noise demote working skills. A second consecutive `merge` verdict on the same
run halts rather than retrying, and files the loss as evidence against the skill's step
graph rather than its content.

Misclassification is itself a tracked defect: a `retrieval` verdict that recurs on the same
skill MUST trigger a Curator proposal to tighten that skill's preconditions, and a `merge`
verdict that recurs on the same skill MUST trigger a Curator proposal to serialise the
implicated steps.

## 17. Attempt isolation

| Rule | Detail |
| --- | --- |
| Snapshot before attempt | `solve` MUST run against a snapshot taken before its first mutation |
| Restore before retry | `evolve` MUST restore the pre-attempt snapshot; retrying on a dirty workspace is invalid |
| Disjoint branch workspaces | `fan_out` clones per branch; branches MUST NOT share a mutable workspace |
| Concurrent step isolation | Steps in the same wave share the attempt's workspace, so their write claims MUST be disjoint (§26.2); a wave is atomic for restore purposes — `evolve` rolls back the whole wave, never half of it |
| Verifier isolation | A `judge` criterion's context is built from artifacts and the criterion text alone; it MUST NOT inherit the solver's transcript (§26.3) |
| Snapshot retention | Retained for the run's lifetime plus the eval retention window, then garbage-collected |
| External effects | `external`-class tool calls are recorded with a compensating action where one exists |
| Uncompensable effects | A skill containing an uncompensable `external` step MUST NOT run in `portfolio` or `shadow` mode |

## 18. Fan-out: portfolio and decomposition

`BranchState`, per `contracts/branch.py`, fixes what the refactor plan flagged as S3: the prior
`Branch` had no status, spend, transcript, or snapshot reference, so `evolve` had nothing to
restore and a merge audit had nothing concrete to attribute a missing input to.

```python
class BranchState(BaseModel):
    branch_id: str
    kind: Literal["portfolio", "decomposition"] = "portfolio"
    strategy: Literal["apply", "adapt", "scratch"]
    subtask: str | None = None     # decomposition only: the part of the work owned
    candidate: dict | None = None
    workspace_ref: str
    snapshot_ref: str | None = None
    transcript_ref: str | None = None
    status: Literal["dispatched", "running", "succeeded", "failed", "timed_out"] = "dispatched"
    resources: list[ResourceClaim] = []
    budget: Budget                 # a division of the parent budget, never a multiple
    spent: Spend = Spend()
    results: list[CriterionResult] = []
    selected: bool = False
    margin: float | None = None    # winner score minus runner-up
    owned_criteria: list[str] = []  # decomposition only: ids this branch is accountable for (§4)
```

Two kinds with different join semantics:

| Kind | Branches | Join | Failure of one branch |
| --- | --- | --- | --- |
| `portfolio` | Competing strategies for the same task | Select one winner | Tolerated; remaining branches still adjudicate |
| `decomposition` | Disjoint parts of the work | All must complete, then synthesise | Blocks synthesis; recorded in the merge audit (§26.4) |

`plan` MAY choose `decomposition` only when the locked criteria can be partitioned: every
branch owns a subset of the required criteria, the subsets are disjoint, and their union is
the full required set. A criterion that no branch owns is a criterion nothing is accountable
for, which is how a decomposed run reports success while missing a requirement. Criteria that
can only be scored on the merged artifact stay with the join and are evaluated after
synthesis; if any exists, the join MUST NOT route to `distill` before scoring them.

Rules: `max_branches` default 3; the parent budget is divided, so fan-out trades latency for
cost-neutral exploration; branches MUST hold disjoint workspaces **and** non-overlapping `write`
or `exclusive` resource claims (§26.2); `join` selects by required-criteria pass count, then by
advisory score, then by lowest cost — a model preference MUST NOT break a tie; losing portfolio
branches are written to the episodic plane as cases, because a validated comparison between
approaches is exactly the evidence the Curator and Practice jobs need.
