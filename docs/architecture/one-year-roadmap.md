# One-year technical roadmap (August 2026 – August 2027)

Companion to [`principal-review-2026-08.md`](principal-review-2026-08.md), which contains the
evidence for every gap cited here. Sequencing follows the same rule as
[`../implementation-plan.md`](../implementation-plan.md): phases are ordered by what each one
lets you **measure**, not by calendar appetite. Every phase lists engineering gates (merge
requirements) separately from research outcomes (never merge requirements, per
[`../assumptions.md`](../assumptions.md) and refactor-plan B7).

## 1. Strategic posture

The build phase is complete: M0–M9 plus security hardening (#39) and go-live wiring (#40) are
on `main`. What is not complete is **evidence**. The system's central claim — that managed
memory compounds — is currently supported by the literature (Ratchet **[F]**, +0.328 on MBPP+
hard-100 with a no-skill control at +0.002) and untested on our own traffic (`a1`, `a2`:
`under evaluation`). A year from now the deliverable is not more architecture; it is a
defensible answer, in our domain, with our harness, to "does it get better, and can you prove
it?"

Resource allocation guidance: ~70% measurement/operations, ~30% new capability, shifting
toward capability only after Phase 2 produces stable intervals.

## 2. Phase 1 (months 0–3): Operator-mode GA

**Goal:** one operator can run Recertia unattended on `repo-chore` work with a real model,
real costs, and injection-hardened tools — the minimum product that can generate truthful
traffic for Phase 2.

Scope (each item closes a P0 gap from the review):

1. **Cost accounting (P0-1).** Pricing table per model id; `ModelResponse.cost_usd` computed
   from token usage on every provider call; `cost_per_solved_task` becomes a real number.
2. **Injection hardening (P0-2).** Fetched content wrapped as untrusted data (delimiters +
   instruction pinning) everywhere it enters a prompt; a command policy gate in front of
   `agent_subtask` (allowlisted prefixes, or operator approval in interactive mode);
   adversarial regression tests with planted instructions inside fetched payloads — the
   test-strategy Adversarial row, now pointed at the real injection surface (OWASP LLM01
   **[S]**).
3. **Bounded observe–act scratch loop (P0-3).** The solver sees command output and proposes
   the next step within the attempt; iteration bound from policy; every step transcripted and
   budget-charged. The loop is a solver property; graph topology does not change.
4. **Manifest pinning (P0-4).** Bootstrap pins provider, model id, index snapshot, and library
   commit into `RunManifest` for every run, CLI and API alike.
5. **Soak and durability (P0-5).** Docker + Postgres soak environment exercised on a weekly
   schedule; documented backup/RPO for `.recertia/`; dashboards consuming the OTel export;
   run-latency and eval-cadence SLOs.
6. **Verifier configuration.** Documented solver/verifier split (distinct credentials
   preferred, distinct model id required); `--verifier` default policy in the go-live doc.

**Done when (engineering gates):** a synthetic run with a recorded fixture shows non-zero
`cost_usd` propagating to `Spend` and to the eval store (CI); a planted-instruction payload
cannot steer `agent_subtask` into a non-allowlisted command (CI); a scratch task that fails
its first command succeeds on a later in-attempt iteration, fully transcripted (CI); every
run manifest is fully populated (CI); the soak environment runs the golden suite weekly on
Postgres without manual intervention (ops gate).

**Research outcomes recorded, not gated:** baseline `reuse_rate`, `first_attempt_success`,
`attempts_to_success`, and true `cost_per_solved_task` on real operator traffic. No lift
claim is made this phase.

**GA criteria for operator mode:** all engineering gates green for four consecutive soak
weeks; zero P0 rows open; one documented incident review exercised (even if tabletop).

## 3. Phase 2 (months 3–6): Measured compounding on repo-chore

**Goal:** resolve `a1` and `a2` — in either direction — and instrument the judge. This is the
phase the entire system exists to enable; everything before it is scaffolding for honest
measurement.

Scope:

1. **Eval cadence (P1-1).** Scheduled runs against the labelled probe set
   (`evals/probes/repo-chore.json`) and golden suite with the ablation control arm at the
   governed rate; weekly `causal_lift` report with Wilson intervals; `retrieval_precision_at_3`
   re-measured on the probe labels.
2. **Judge false-pass canary (P1-2, assumption `a4`).** Planted-failure artifacts scored by
   the verifier on a schedule; false-pass rate reported per model version; alert past a
   configured threshold. This operationalizes Blind Curator **[B]** before the failure mode
   can silently disable retirement.
3. **Curation gap (P1-4).** `curation_gap` reported per provenance class — the direct,
   in-domain test of SkillsBench's +0.0pp self-authored result **[B]**.
4. **Practice loop closed (P1-5).** Scheduled Practice job consuming recorded one-off
   clusters; `practice_conversion` reported; curriculum excluded from user-facing metrics.
5. **Evidence-floor study (`a2`).** Certification-trial accumulation rates per skill; the
   answer to "does most of the library sit below the floor indefinitely?" is a finding either
   way.

**Done when (engineering gates):** the weekly lift report is generated automatically and
correctly reports "not established" on any week where the interval spans zero; the canary
produces a false-pass number per verifier model version (CI on synthetic planted failures,
ops on the real schedule); `curation_gap` appears in the metrics export; Practice conversion
is tracked with its own budget.

**Research outcomes (the point of the phase):** `a1` moves to `supported` or `refuted` with
a stated interval; `a2` moves to `supported` or `refuted` with observed accumulation rates;
`a4` moves to `under evaluation` with the first measured canary rates. A negative `a1` result
halts Phase 3 scope expansion and triggers a design review of the curation bottleneck —
that is the B7 machinery working, not a project failure.

## 4. Phase 3 (months 6–9): Library economics

**Goal:** the improvement plane runs on evidence it collected itself — Curator proposals
justified by trajectory replay and contribution data, not by schedule.

Scope:

1. **Trajectory replay as Curator evidence (P1-3).** Replay packs (`retrieval_only` first,
   per ADR-0011) attached to Curator proposals and promotion packets; additive evidence only;
   golden gate remains mandatory.
2. **Step-graph proposals from real transcripts.** `parallelise` / `serialise` driven by the
   fake-edge threshold on production transcripts; each proposal reports expected
   `parallel_speedup` beside `merge_gap_rate` — never speedup alone.
3. **Composition exercised (M8 in production).** At least one parent skill composes pinned
   children on real traffic; `mean_composition_depth` tracked against library size (the
   Dynamic Agent Skills survey's **library trajectory** metric **[F]**).
4. **Retirement observability.** `retirement_reversal_rate`, `active_cap_pressure`, and
   contribution distributions on a dashboard; harsh-configuration alarms (Ratchet A4 **[F]**
   is the named failure mode).
5. **Correction Miner on reviewer edits.** Reviewer-edit clusters become T2 proposals; every
   proposal classified to a tier and ledger-recorded — this is also the longitudinal test of
   `a3`.

**Done when (engineering gates):** a Curator proposal lands with a replay pack attached and
the pack is reproducible from the trajectory store (CI); a genuinely serial-for-no-reason
skill is parallelised by proposal with no golden regression (e2e); quarantining a composed
child provably benches its parents (e2e); retirement decisions display their evidence floor
and interval in the ledger (CI).

**Research outcomes:** `library_yield` trend (the anti-vanity metric), `retrieval_decay`
early-warning trend, composition's effect on coverage growth.

## 5. Phase 4 (months 9–12): Second domain and the multi-tenant readiness gate

**Goal:** prove generality on `research-synthesis`, then decide — with criteria fixed in
advance — whether multi-tenant is worth building at all.

Scope:

1. **Second domain, unchanged runtime.** `research-synthesis` runs on the existing graph,
   schemas, and services with **no structural change**; any change required is logged as a
   design defect and fixed in the shared layer, not patched domain-locally (M9's done-when,
   now executed against real traffic; golden fixtures already exist under
   `evals/golden/research-synthesis/`).
2. **Scope model exercised.** Cross-scope promotion with redaction; planted-secret crossing
   test; tenant-private memory verified absent from other scopes' retrieval.
3. **Postgres soak on a real snapshot (P2-1)** and quota accounting (P2-3).
4. **Production readiness assessment.** Threat model re-review (all §5 deltas from the
   review closed or explicitly accepted); break-glass procedure; key rotation; deployment
   topology; SLOs; NIST AI RMF Govern/Map documentation for the tenant surface **[S]**.
5. **The gate.** Multi-tenant GA proceeds only if: operator mode has been GA for a full
   phase; `a1` is `supported` in at least one domain (a system that cannot demonstrate lift
   should not multiply its blast radius); all P2 rows closed; and a written threat model is
   signed by someone other than its author. Otherwise multi-tenant defers, and the year ends
   with a two-domain single-operator product — a good outcome.

**Done when (engineering gates):** `research-synthesis` tasks run on the unchanged runtime
(CI + soak); cross-scope redaction test passes; the readiness assessment document exists with
every item either closed or accepted-with-owner.

**Research outcomes:** second-domain `reuse_rate` and `causal_lift` reported; "not
established" is an acceptable, passing result per B7.

## 6. Operating cadence (cross-cutting)

| Cadence | Ritual | Artifact |
| --- | --- | --- |
| Weekly | Metrics review: lift report, canary rates, cost per solved task | Auto-generated report; decisions logged |
| Monthly | Assumptions register review (`a1`–`a4` statuses) | Updated `assumptions.md`; status changes are commits, not conversation |
| Quarterly | Threat-model refresh; ADR review for any settled-decision challenges | Updated threat model; ADRs for genuine reversals only |
| Per promotion | Golden gate + evidence packet (replay pack from Phase 3) | Ledger entry |
| Per incident | Blameless review; control-plane fix preferred over prose | Incident doc linked from the run id |

## 7. Staffing and build-vs-buy notes

- Phase 1–2 needs one engineer with full context more than it needs three without; the
  measurement code is subtle exactly where it is load-bearing.
- Buy observability (dashboards, alerting); keep the eval harness in-house forever — it is
  the product's claim to honesty.
- Model-provider failover (P2-5) is a deliberate-absence candidate: two providers doubles the
  judge-bias surface (canary must run per provider × model) for an availability benefit a
  single operator may not need. Decide at the Phase 4 gate with data, not in advance.
- If a second domain champion is available by Phase 4, the highest-leverage hire is the
  person who labels probe sets and reviews Curator proposals — curation is the bottleneck the
  literature keeps naming (Ratchet **[F]**; Dynamic Agent Skills **[F]**).

## 8. Success criteria for the year

1. Operator mode GA with cost, injection, and soak gates green — a system one person can
   trust unattended.
2. `a1` and `a2` resolved with intervals, in either direction, on real traffic.
3. `a4` instrumented: the judge's false-pass rate is a number we watch, not a hope we hold.
4. The improvement plane proposing from its own evidence (trajectory replay, contribution),
   with the golden gate intact.
5. A second domain on the unchanged runtime, and a multi-tenant decision made by criteria
   fixed before the evidence was in.

## 9. Engineering status (as of roadmap-remaining implementation)

Engineering gates that can land in CI are implemented; research outcomes stay harness-ready
and must not be marked `supported` without real traffic (B7).

| Phase | Engineering landed | Still ops / research |
| --- | --- | --- |
| 1 Operator GA | Cost, injection, observe–act, manifest, soak compose + weekly workflow, tabletop doc | Four consecutive soak weeks; baseline metrics on real traffic; live incident (or completed tabletop log) |
| 2 Measured compounding | `recertia metrics` + `scripts/weekly_metrics_report.py`; judge canary fixtures; `curation_gap` / `practice_conversion` on `MetricReport`; Practice reads `one_off_log` | Scheduled probe runs on live traffic; `a1`/`a2`/`a4` status changes with intervals |
| 3 Library economics | Trajectory emit + ReplayPack on Curator; `parallelise`/`serialise`/`correction` jobs + CLI; retirement / composition / pressure fields | Real-traffic composition; library_yield / retrieval_decay trends |
| 4 Second domain + tenant gate | research-synthesis fixture gate; planted-secret scope e2e; `QuotaStore`; [`production-readiness.md`](production-readiness.md) | Signed threat model; multi-tenant go/defer decision |

## 10. References

Phase mapping to the tracked literature: Phase 1 — Falsifiable Release Gates
(arXiv:2607.13070 **[B]**) for pre-declared GA suites; OWASP LLM Top 10 **[S]** for the
injection surface. Phase 2 — SkillsBench (arXiv:2602.12670 **[B]**, `a1`); Ratchet A4
(arXiv:2605.22148 **[F]**, `a2`); Blind Curator (arXiv:2607.07436 **[B]**, `a4`); Not All
Skills Help (arXiv:2606.15390 **[B]**) for per-skill causal contribution; PACE
(arXiv:2606.08106 **[B]**) for why the acceptor, not the proposer, is where rigor lives.
Phase 3 — ATDP/trajectory replay (arXiv:2607.01120 **[F]**, ADR-0011); Dynamic Agent Skills
(arXiv:2607.10113 **[F]**) for library-trajectory metrics; Trace2Skill
(arXiv:2603.25158 **[B]**) for trace-driven pruning with a gate. Phase 4 — Voyager
(arXiv:2305.16291 **[F]**) as the generality precedent; NIST AI RMF 1.0 **[S]** for the
readiness assessment frame.
