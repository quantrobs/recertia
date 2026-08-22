# Recertia Architecture: 11. Measurement integrity

## 11. Measurement integrity

The failure mode that kills self-improving systems is not incompetence, it is self-deception:
the system optimises its own scorecard. Four structural defences, plus
[ADR-0003](../adr/0003-criteria-preregistration.md).

### 11.1 Pre-registered criteria

Criteria are locked at `intake`, **before** `solve` runs, and their hash is recorded in the
manifest. A solver cannot tailor the target it is measured against, and a distiller cannot
retrofit criteria that its own transcript happens to satisfy. Criteria may be *added* during
a run only as advisory (`weight < 1.0`); required criteria are immutable once locked.

Where the caller supplies no criteria, a **critic** pass proposes them from the task intent
before solving, in a separate context from the solver. Same reason: independence.

These are `TaskCriterion`s, and a chosen skill is never a source for them — no skill has been
selected yet at `intake`. A skill's own certification criteria (`SkillCertificationCriterion`)
are a separate type on a separate timeline: authored at `distill`, validated on independent
certification runs before promotion, and never merged into a run's required set. See the
[ADR-0003 amendment](../adr/0003-criteria-preregistration.md#amendment-two-criteria-timelines-2026-07-30)
and `specifications/memory-composition-and-criteria.md` §15.4.

### 11.2 Criterion sensitivity proofs

A criterion that never fails is decoration, and a suite of them makes everything look solved.
Every criterion must demonstrate that it **rejects** a known-bad artifact — the pre-solve
workspace, a mutated artifact, or a recorded prior failure — before it counts toward
promotion. This is mutation testing applied to validators. Criteria without a sensitivity
proof are advisory only.

### 11.3 Eval firewall and run manifest

Golden tasks must never be distilled from, or evals measure memorisation instead of
generalisation. Runs on eval fixtures are flagged and blocked at `distill`. Every run records
a manifest — model and version, tool versions, index snapshot, library commit, criteria hash,
seed — so any measurement is tied to an exact system state and can be replayed.

### 11.4 Ablation arm

Golden sets prove capability under lab conditions; they cannot prove that retrieval helps in
production, because retrieved-skill runs and scratch runs face different task mixes. So a
small sampled fraction of production runs (default 5%, task-class stratified, never on
destructive tasks) runs with retrieval suppressed as a control. That control is what turns
"first-attempt success went up" into "retrieval caused it", and it is the only defence
against the most comfortable failure mode: a library that grows, metrics that drift upward
for unrelated reasons, and nobody able to tell the difference.

The control arm supplies the class-level `RetrievalAblationEffect` that answers whether
retrieval helps this task class. Per-skill retirement uses a separate randomized
shadow-versus-suppression contrast (§7.2) — not a class baseline subtracted from a selected
skill — so the same measurement program serves both questions without conflating them.

### 11.5 Multi-run variance and the independent-run floor

A Newcombe–Wilson interval that excludes zero is not enough. `CausalLiftResult` also
carries per-arm and (when paired windows exist) per-lift `RunVariance`: sample std-dev,
best rate, worst rate, and the absolute best–worst gap. Independent runs are
**observation/trial counts**, not snapshot counts, so a 100-trial window can still
establish lift. Below the policy floor (`min_independent_runs`, default 5) the status is
`low_run_count` even if the interval excludes zero. `recertia lift` prints the variance
fields and refuses established language below the floor. Per-run Bernoulli vectors live
in `EvalStore` so the numbers recompute from storage.

### 11.6 Faithfulness interventions (eval-only)

Condensed-memory *use* is falsifiable. Four controlled interventions — `empty`, `corrupt`,
`irrelevant`, `filler` — replace the retrieved skill body in memory (never on the
production retrieve path). The harness records first-attempt success against the
unmodified baseline and decision-level trajectory divergence (event-kind Jaccard and
Levenshtein). The faithfulness score is the fraction of interventions that move success
or the trajectory. Observation rows are tagged `strategy=faithfulness:<name>` and treated
as eval fixtures so they cannot enter lift. `recertia.evals.interventions` and
`recertia.evals.faithfulness` are T3 and import-forbidden from `nodes/` and `jobs/`.
The production flag `faithfulness_interventions_enabled` is false.

### 11.7 Applicability and specificity before promotion

Distillation injects the current environment model (tools from the registry) and the
locked `TaskCriterion[]` summary. Before `candidate` / `approved`, an applicability gate
rejects skills that name unavailable tools, whose success claims cannot be evaluated by
locked criteria, or that are structural near-duplicates of retired / quarantined /
benched / low-contribution skills. Rejections are `applicability_reject` ledger entries
and do not grow `library_yield`. Specificity lint (`SPEC` / `VAGUE`) is an error on
draft/candidate/shadow and a warning on already-approved seeds, so the seed library stays
green while new drafts must carry concrete `failure_modes`.

