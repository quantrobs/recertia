# Recertia Architecture: 12. Failure taxonomy

## 12. Failure taxonomy

Blind retry is a waste of budget. `classify_failure`'s only precondition is that a failure
signal was raised — by the orchestrator, solver, validator, or join — not that a required
criterion failed; most classes below have no result vector to have failed at all
([ADR-0008](../adr/0008-optional-join-and-failure-signals.md)). It assigns a class, and the class
dictates `evolve`'s move:

| Class | Signal | `evolve` move |
| --- | --- | --- |
| `environment` | Setup or dependency failure before real work | Repair environment, do not touch strategy; does not count against skill trust |
| `tool` | Tool error or known flake in the affordance plane | Retry with backoff or substitute tool |
| `retrieval` | Applied skill's preconditions held but it was inapplicable | Drop candidate, re-retrieve, tighten the skill's preconditions |
| `plan` | Strategy was wrong in kind | Switch strategy, escalate model tier |
| `execution` | Right plan, wrong edit | Patch artifacts using criteria output |
| `criteria` | Criteria contradictory or unsatisfiable as written | Route to `record_dead_end`, escalate to human; never relax criteria |
| `budget` | Ran out of room | Route to `record_dead_end`, report the frontier reached |
| `merge` | A merge audit found missing inputs, or a resource claim timed out (§5.10, §5.6) | Re-dispatch only what never arrived, once; a claim timeout re-runs the wave serially |

Three consequences matter. Environment and tool failures must not damage a skill's trust
score — otherwise flaky infrastructure silently quarantines good skills. `criteria` failures
escalate to a human rather than being repaired by the system, since self-repair of the
scorecard is precisely what §11 exists to prevent. And `merge` is separated from `execution`
because the two look identical from the outside and want opposite repairs: an execution
failure means the work was wrong, while a merge failure means some of the work never came
back. Retrying the whole attempt on a lost branch wastes the branches that succeeded, and
charging trust for it would let executor noise demote skills that did their job.

## 13. Drift and non-stationarity

Nothing here is stationary: models are upgraded, tools change, repos evolve. Controls:

- **Environment fingerprint** in preconditions and certification, so a skill is not applied
  in an environment it was never validated in.
- **Model-version gate:** a skill's certification records the model it was validated on; a
  model upgrade marks affected skills `needs_recert` rather than trusting them silently.
- **Scheduled recertification** (§8.4) with staleness surfaced in retrieval ranking.
- **Trust decay:** trust weight decays with time since last successful application, so an
  old unverified skill does not outrank a fresh one on reputation alone.

## 14. Meta-learning and the self-modification boundary

The system improves its own machinery, which is exactly where a self-improving system can
become unsafe or unmeasurable. So capability is tiered explicitly
([ADR-0005](../adr/0005-self-modification-boundary.md)):

| Tier | Scope | Change mechanism |
| --- | --- | --- |
| **T0 — autonomous** | Trust scores, affordance aggregates, episodic cases, retrieval caches | Written by runs; derived, revertible, no gate |
| **T1 — policy-gated** | New skill versions, facts, curator proposals, shadow promotions | Automatic promotion only with eval evidence and zero regressions |
| **T2 — human-gated** | Authoring prior and distiller guidance, criteria templates, retrieval thresholds, routing and escalation ladder, budget defaults, values of `active_cap` / `retirement_threshold` / `evidence_floor` / `max_parallel_steps` / `layer_threshold` | Versioned config; change requires human approval plus an eval comparison |
| **T3 — never autonomous** | Tool registry with side-effect classes and declared resource claims, sandbox policy, promotion thresholds, the ablation rate, the graph topology, enforcement of judge isolation and merge audits, the *finiteness* of the active cap and retirement threshold, this boundary | Human-authored code or config review only |

The rule behind the table: **the system may not modify the mechanisms that measure or
constrain it.** A system that can lower its own promotion bar, shrink its own control arm, or
grant its own tool permissions has no trustworthy metrics and no meaningful containment —
and it would get there by optimising honestly for the objective it was given.

T2 changes are also improvements and must be evidenced the same way: propose, run the golden
sets against both configs, show lift, then a human approves.

## 15. Safety, integrity, failure model

### 15.1 Provenance integrity

Every memory write appends to a hash-chained ledger: actor, run, artifact hash, previous
head. Because the system writes its own memory, "who wrote this and on what evidence" must be
tamper-evident rather than merely logged, and a corrupted or poisoned history must be
detectable after the fact.

### 15.2 Memory as data, never instructions

Retrieved content is partly model-authored and partly derived from untrusted tool output, so
treating it as instruction is a prompt-injection channel straight into durable state. Skills
carry structured steps with tool references, not free-form imperative prose. Retrieved facts
and cases enter the solver context labelled as untrusted evidence. Tool arguments come from
bound parameters validated against the schema, never from concatenated memory text.

### 15.3 Secret and PII hygiene at write time

Distillation generalises from a real transcript, which may contain credentials, tokens, or
personal data. Store-time scanning and scrubbing is mandatory, and a draft failing the scan
is rejected rather than sanitised silently — memory is long-lived, and a leak into it is
worse than a leak in a log.

### 15.4 Scope and promotion across scopes

Facts and skills carry a scope: `run` → `project` → `org` → `global`. Cross-scope promotion
requires review and redaction, which keeps context learned in one project from silently
applying — or leaking — into another.

### 15.5 Risk table

| Risk | Control |
| --- | --- |
| Bad skill becomes default | Lifecycle gates, shadow trials, non-`judge` criterion required |
| Confidently wrong retrieval | Preconditions drop candidates, score floor, `plan` may reject all, `retrieval` failure class tightens preconditions |
| Library entropy and retrieval decay | Curator compaction and abstraction, `library_yield`, retrieval precision tracked over snapshots |
| Library drift: growth silently erodes quality | Bounded active cap plus contribution-score retirement give a floor; unbounded growth has none (§7.2) |
| Over-pruning, which measures worse than no library | Evidence floor before any retirement, loose threshold, reversible benching, `active_cap_pressure` |
| Self-distilled skills underperforming human-curated ones | `curation` provenance with a higher evidence bar for self-distilled; Miner treated as a primary quality source |
| Criteria gaming | Pre-registration, sensitivity proofs, criteria changes are reviewable diffs, `criteria` failures escalate |
| Metric self-deception | Ablation control arm, eval firewall, run manifests, calibration scoring |
| Attribution illusion | Causal lift alongside trust; environment and tool failures excluded from trust |
| Silent regression on evolution | Golden-set gate before promotion, transitive invalidation, lineage revert |
| Drift and rot | Environment fingerprints, model-version gates, scheduled recertification, trust decay |
| Dirty retries | Per-attempt workspace snapshot and restore |
| Hidden edges through shared resources | Declared resource claims; overlapping write or exclusive claims forbid concurrency (§5.6) |
| Silent partial merges | Expected-versus-received audit at every fan-in; flag or fail, never proceed quietly (§5.10) |
| Context collapse at synthesis | Layered fan-in: batch, summarise, combine; code-based reduction where mechanical |
| Judges agreeing with the work rather than checking it | Fresh context for model-scored criteria; distinct lenses across judges (§5.7) |
| Biased judges silently disabling retirement | Contribution scored from required non-`judge` criteria only (`references.md` §1.8); a skill with no such criterion has `contribution = null` |
| Runaway loops or cost | Budgets, no-progress detection, escalation ladder, branch caps |
| Destructive tool use | Side-effect classes, sandboxing, approval gates, no uncompensable effects in portfolio or shadow |
| Memory poisoning and injection | Memory-as-data discipline, hash-chained ledger, provenance-weighted trust |
| Secret leakage into memory | Store-time scanning, rejection rather than silent scrubbing |
| Unsafe self-modification | T0–T3 boundary; T3 is code review only |

Quarantine is reversible and additive: it marks versions suspect and preserves history, so a
wrong quarantine costs retrieval quality temporarily but never loses work.
