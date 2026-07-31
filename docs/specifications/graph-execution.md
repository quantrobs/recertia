# Fandea Specifications: 3. Graph state

## 3. Graph state

The state object threaded through every node, generated from
[`contracts/run.py:RunState`](../../contracts/run.py). Nodes return a **delta**, never a mutated
copy, and the orchestrator applies deltas so that every transition is diffable.

```python
class RunState(BaseModel):
    run_id: str
    task: Task
    manifest: RunManifest = RunManifest()   # model, tools, index snapshot, criteria hash, seed
    arm: Literal["treatment", "control", "shadow", "practice"] = "treatment"

    # criteria, locked before solving (§15). TaskCriterion only — never a chosen skill's
    # SkillCertificationCriterion; see the ADR-0003 amendment and §15.
    criteria: list[TaskCriterion] = []      # required set; immutable after intake
    criteria_locked_at: datetime | None = None
    advisory_criteria: list[TaskCriterion] = []

    # retrieval — federated bundle across memory planes (§13)
    bundle: MemoryBundle = MemoryBundle()   # skills, facts, cases, dead_ends, tool_cautions
    chosen: SkillCandidateRef | None = None
    strategy: Literal["apply", "adapt", "scratch", "portfolio", "decomposition", "abstain"] | None = None
    strategy_reason: str | None = None
    predicted_success: float | None = None  # scored for calibration (§23)

    # solving
    attempt_no: int = 0
    branches: list[BranchState] = []        # populated under fan-out strategies (§18)
    artifacts: list[Artifact] = []
    transcript_ref: str | None = None
    workspace_snapshots: list[WorkspaceSnapshot] = []
    step_waves: list[StepWave] = []         # step ids executed concurrently, in order (§26.1)
    resource_conflicts: list[ResourceConflict] = []

    # validation
    results: list[CriterionResult] = []     # latest attempt only
    results_history: list[list[CriterionResult]] = []
    certification_observations: list[CriterionResult] = []  # advisory only; see §15.4
    merge_audits: list[MergeAudit] = []     # one per fan-in, expected vs received (§26.4)
    failure_signal: FailureSignal | None = None   # raised explicitly; classify_failure's precondition (§16, ADR-0008)
    failure: FailureVerdict | None = None   # class + evidence, assigned by classify_failure (§16)

    # learning
    draft: dict | None = None
    facts_extracted: list[dict] = []
    affordance_updates: list[dict] = []
    reusability: ReusabilityVerdict | None = None
    written_versions: list[dict] = []

    # control
    budget: Budget = Budget()
    spent: Spend = Spend()
    route_log: list[RouteEntry] = []        # (node, decision, reason) — the audit trail
    terminal: Literal["solved", "unsolved", "abstained", "rejected", "error"] | None = None
```

`results_history` exists to make no-progress detection possible: if the newest result
vector equals the previous one, `evolve` MUST NOT route back to `solve`.

`arm` determines measurement handling: `control` runs suppress retrieval (§19), `shadow`
runs MUST NOT affect the caller's result, and `practice` runs MUST be excluded from
user-facing metrics.

`certification_observations` exists because a run's artifact is free to score against the
applied skill's certification criteria too — but that score is advisory telemetry feeding
`SkillStats`/`needs_recert` (§20) and MUST NOT gate any route below. It is populated by
`validate`; nothing reads it before `distill`/`review` except the improvement plane, offline.

## 4. Node contracts

Every node is `(state, services) -> NodeOutput`, where `NodeOutput` carries a state delta,
a route, and a reason string. Nodes MUST be side-effect free with respect to state and MUST
route only to declared successors. Fifteen nodes — see
[ADR-0008](../adr/0008-optional-join-and-failure-signals.md): `join` is conditional and
`quarantine` is split into `record_dead_end` and `reject_draft`; marking a *stored skill
version* harmful is not a task-plane action at all (§2.5, §20). The full route table is data in
[`contracts/graph.py`](../../contracts/graph.py), exhaustively tested by
[`tests/contracts/test_route_completeness.py`](../../tests/contracts/test_route_completeness.py).

| Node | Preconditions | Postconditions | Legal routes |
| --- | --- | --- | --- |
| `intake` | Request validated | `task` set, budget + model tier resolved, `manifest` recorded, `criteria` locked with hash (`TaskCriterion` only) | `retrieve` |
| `retrieve` | `task` set, criteria locked | `bundle` populated across planes, preconditions evaluated; empty when `arm == "control"` | `plan` |
| `plan` | `bundle` present (possibly empty) | `strategy`, `strategy_reason`, `predicted_success` set | `solve`, `fan_out`, `finalize` (abstain) |
| `fan_out` | `strategy` is `portfolio` or `decomposition` | `branches` created with `kind` set, disjoint workspaces, non-overlapping write claims, divided budget, and (decomposition) `owned_criteria` partitioning the locked set | `solve` |
| `solve` | `strategy` set, budget not exhausted, clean workspace snapshot taken | Steps executed in `depends_on` order with bounded concurrency (§26.1); `transcript_ref`, `artifacts`, `step_waves` set; `attempt_no` incremented; MAY raise a `FailureSignal` directly (environment/tool/budget) without ever reaching `validate` | `validate`, `classify_failure` |
| `validate` | `transcript_ref` set | `results` set and appended to history; `certification_observations` scored; `judge` criteria scored in fresh contexts (§26.3); a required-criterion failure raises `failure_signal` | `join` (if `branches` non-empty), `distill`, `classify_failure` |
| `join` | `branches` non-empty; every dispatched branch has terminated (result, error, or timeout) | `merge_audits` appended; portfolio winner selected by result vector then cost, decomposition inputs reduced then synthesised; losers written to episodic memory; a gap raises `failure_signal` | `distill`, `classify_failure` |
| `classify_failure` | `failure_signal` is set (ADR-0008; not "some required criterion failed" — most classes have no result vector at all) | `failure` set with class + evidence | `evolve`, `record_dead_end` |
| `evolve` | Budget remains, progress observed, `failure` set | Repair move applied per §16; workspace restored; a budget decremented | `solve` |
| `distill` | All required criteria passed, `arm != "control"`, task is not an eval fixture | `draft`, `facts_extracted`, `affordance_updates`, `reusability` set | `review`, `finalize` |
| `review` | `draft` reusable | Decision recorded | `store`, `reject_draft` |
| `store` | Decision is approve, hygiene scan passed | `written_versions` set; index updated; ledger appended | `finalize` |
| `record_dead_end` | `failure` set | Failed run recorded to episodic memory with `why_failed`; skill trust untouched unless `failure.counts_against_trust` | `finalize` (`terminal="unsolved"`) |
| `reject_draft` | Draft rejected by policy or human | Rejection recorded with the diff for the Correction Miner (§20); no version written | `finalize` (`terminal="rejected"`) |
| `finalize` | — | `terminal` set | — |

### 4.1 Routing predicates

```text
plan     → finalize         : strategy == "abstain"                  (terminal="abstained")
plan     → fan_out          : strategy in {"portfolio", "decomposition"}
solve    → classify_failure : failure_signal is set AND no result vector yet (ADR-0008)
solve    → validate         : transcript_ref is set (attempt completed)
validate → join             : branches is non-empty
validate → distill          : branches is empty AND every criterion with weight >= 1.0 passed
                              AND failure_signal is unset
validate → classify_failure : branches is empty AND (some required criterion failed
                              OR failure_signal is set)
join     → distill          : every merge_audit.received >= merge_audit.expected with no
                              missing ids, AND every criterion with weight >= 1.0 passed
join     → classify_failure : otherwise (including an incomplete merge)
classify → evolve           : spent.attempts < budget.max_attempts
                              AND results != previous results
                              AND failure.failure_class not in {"criteria", "budget"}
classify → record_dead_end  : otherwise
distill  → review           : reusability.verdict == "reusable"
distill  → finalize         : reusability.verdict == "one_off"   (recorded as evidence)
review   → store            : policy auto-approves OR human approved
review   → reject_draft     : human or policy rejected
```

`join` exists only on the fan-out path (`branches` non-empty). The ordinary, single-attempt
path used exclusively through M0–M5 routes `validate` directly to `distill` or
`classify_failure` — this is Option 1 from
[`refactor-plan.md`](../refactor-plan.md) B3, chosen definitively; see
[ADR-0008](../adr/0008-optional-join-and-failure-signals.md). `MergeAudit` has no `.complete`
field; the predicate above is the real one, over `expected`/`received`/`missing`.

A `criteria` failure class MUST route to `record_dead_end` with a human escalation flag, never to
`evolve`: the system does not repair its own scorecard (§15). Marking the *skill version*
`quarantined` never happens from this table — see §2.5 and §20.

Criteria with `weight < 1.0` are advisory: they are recorded and surfaced to review, but
they do not block `distill`. This is what keeps `judge` criteria useful without letting a
model's opinion gate promotion.
