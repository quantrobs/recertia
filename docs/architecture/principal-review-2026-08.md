# Principal architecture review — August 2026

External review of the Recertia system at commit `5ed5e3b` (post-#40 go-live wiring), conducted
against the consultant mandate: what to build, what not to build, how the system must be
structured for measurement and control, and how to ship AI that is reliable, governable, and
economically defensible.

Citation convention: papers reuse the verification tags of [`../references.md`](../references.md)
(**[F]** fetched and read; **[B]** bibliography-only). Public standards and vendor documentation
are marked **[S]** (specification/public documentation, weighted as requirements, not evidence).

## 1. Scope and method

Read in full: `contracts/` (run, criteria, skill, graph, resources, profiles), `src/recertia/`
(engine, nodes, solver, validation, memory planes, retrieval, evals, jobs, api, cli),
`docs/` (ADRs 0001–0011, implementation plan, specifications, assumptions register, references),
`research/` (scored preprint survey), tests (319 passing at review time), CI.

Posture: claims below were verified against code, not against documentation. Where a document
and the code disagree, the gap is listed as a finding.

## 2. Verdict

The architecture is sound, unusually measurement-honest, and structurally complete through
M0–M9. The risks that remain are not design risks; they are **operational and evidential
risks**. The system has never run under real traffic with a real model: the two assumptions
that decide whether the product thesis is true (`a1` causal lift, `a2` evidence-floor
reachability) are `under evaluation`, and the harness that would resolve them has no traffic
cadence, no live soak environment, and — on real providers — no cost accounting.

The next twelve months should therefore be allocated roughly 70% to measurement and operations
and 30% to new capability. Multi-tenant work is a Phase-4 gate decision, not a parallel
workstream. The detailed plan is the companion document
[`one-year-roadmap.md`](one-year-roadmap.md).

**Update (same engagement):** Phase-1 P0 engineering gates P0-1…P0-5 are implemented on
`main` via the operator-GA follow-up (cost accounting, command policy + untrusted delimiters,
observe–act scratch loop, run-manifest pinning, soak/backup guidance in
[`go-live.md`](go-live.md)). Remaining Phase-1 work is the weekly soak ops cadence, not more
code.

## 3. What is settled — stop re-litigating

These decisions are correct, implemented, and enforced. Re-opening them costs more than any
plausible improvement:

1. **Contracts as the structural source of truth** (ADR-0009). Pydantic models, generated
   schemas, semantic profiles, zero-drift CI. This is the strongest structural asset in the
   repository; treat any proposal to add a parallel source of truth as a defect.
2. **The engineering-gate / research-outcome split** (refactor-plan B7, `assumptions.md`).
   The hygiene CI that fails a done-when citing an unverified assumption is rarer and more
   valuable than most teams' entire eval story. Keep it absolute.
3. **The T0–T3 self-modification boundary** (ADR-0005) with import-boundary tests. No external
   precedent exists (`a3`, untested); that is a reason to keep the boundary conservative, not
   to relax it.
4. **Criteria integrity**: pre-registration, hash-bound sensitivity proofs, advisory downgrade
   of unproven criteria, fresh-context judges with distinct lenses and recorded context hashes,
   and the solver–judge identity check (`validate.py` lines 115–118 enforce all of these at
   runtime, not just in prose).
5. **Library lifecycle**: version/status/stats split (ADR-0007), bounded active set with
   reversible benching, evidence floor before contribution retirement (ADR-0006, from Ratchet's
   over-pruning ablation **[F]**), contribution restricted to non-`judge` required criteria
   (Blind Curator **[B]**).
6. **Attempt isolation and fan-out integrity**: snapshot/restore with differential sync,
   resource-claim scheduling, wave rollback, merge audits.
7. **Security remediation (#39)** and **go-live wiring (#40)**: path containment, id
   validation, container sandbox defaults, structured API keys with scopes and rate limits,
   model provider factory with fail-loud scratch, seed proof hashes with CI lint.

## 4. Production gaps, prioritized

Severity is measured against the single-user operator GA first, multi-tenant second.

### P0 — blocks operator-mode GA

| # | Gap | Evidence | Consequence if unaddressed | Fix (roadmap phase) |
| --- | --- | --- | --- | --- |
| P0-1 | **Cost accounting is blind on real providers** | `solver/providers.py` returns `cost_usd=0.0` for both Anthropic and OpenAI responses | `Budget.max_cost_usd`, fan-out budget division, portfolio cost tie-breaks, and `cost_per_solved_task` (the unit-economics metric) all read zero. The Bun-scale failure mode from [`references.md` §1.7](../references.md) — $165k of agent usage under supervision — is precisely what an unpriced loop enables | Pricing table per model id; cost computed from token counts per response; CI fixture asserting non-zero cost propagation through `Spend` (Phase 1) |
| P0-2 | **Prompt-injection path: `fetch` → `agent_subtask`** | `registry.py`: fetched changelog text is interpolated verbatim into the repair prompt; the model's proposed command executes through the shell tool | With the container backend this is confined; with `--local-exec` an upstream changelog author gets command execution on the operator's host. This is the canonical indirect-injection pattern (OWASP LLM Top 10, LLM01 **[S]**) and it is one indirection away from `bump-python-dep`, the flagship seed skill | Treat all fetched content as untrusted data: delimit + instruction-pin in prompts; a command policy gate on `agent_subtask` (allowlisted prefixes or operator approval); an adversarial regression test with a planted instruction inside a fetched payload, per the test strategy's Adversarial row (Phase 1) |
| P0-3 | **Scratch solving is single-shot** | `_resolve_script` in `nodes/solve.py`: one prompt, one command line, no observation of the result before `validate` | Unscripted runs cannot demonstrate the observe–act competence the memory planes exist to compound; first-attempt success on real tasks will be noise, poisoning the `a1` measurement with an artificially weak treatment arm | Bounded observe–act loop inside an attempt (model sees command output, proposes next command), each step transcripted and budget-charged; loop bound from policy, not from the model (Phase 1) |
| P0-4 | **Run manifest unpinned on operator runs** | `engine.start(manifest=None)` on CLI/API paths; intake pins only `criteria_hash`; `model`, `model_version`, `index_snapshot_id`, `library_commit` stay null | Every M4 measurement property ("any measurement ties to an exact state", specs §11.3) silently degrades on real traffic — lift numbers become attributable to nothing | Bootstrap pins provider, model id, index snapshot, and library commit into the manifest at `start()`; CI test that a CLI run's manifest is fully populated (Phase 1) |
| P0-5 | **No live soak or durability story** | SQLite + JSONL + filesystem snapshots on one host; Postgres dialect exists but unsoaked; OTel JSONL export exists but feeds no dashboard; no documented backup/RPO for `.recertia/` | The plan's own "remaining work" line names this; an operator losing `.recertia/` loses ledger, checkpoints, episodic memory, and eval history at once | Soak environment (Docker + Postgres) exercised weekly; documented RPO/backup; dashboards consuming the OTel export; SLOs for run latency and eval cadence (Phase 1) |

### P1 — measurement integrity under real traffic

| # | Gap | Why it matters | Fix (roadmap phase) |
| --- | --- | --- | --- |
| P1-1 | No eval **cadence**: ablation sampling and golden regression run in CI on synthetic fixtures, never on a schedule against real traffic | `a1`/`a2` cannot resolve without scheduled data collection; "under evaluation" becomes a permanent state, which is indistinguishable from the claim being false | Scheduled eval lane (cron/CI-scheduled runs with the control arm at the governed rate), weekly `causal_lift` report with Wilson intervals (Phase 2) |
| P1-2 | No judge false-pass **canary** | Blind Curator's central result **[B]**: false-pass bias past a sharp threshold silently disables contribution retirement, and the system still looks healthy. Judge isolation is necessary, not sufficient — an isolated judge can still be biased | Planted-failure artifacts scored by the verifier on a schedule; measured false-pass rate per model version; tracked as new assumption `a4` (Phase 2) |
| P1-3 | Trajectory replay (ADR-0011) not yet used as Curator evidence | The counterfactual substrate exists (`trajectory/`, `replay/`) but promotion packets still rest on golden gates alone; offline replay was the point of building it | Replay packs attached to Curator proposals and promotion decisions; additive evidence only, golden gate still mandatory (Phase 3) |
| P1-4 | `curation_gap` named in the risk table but not reported | It is the direct test of SkillsBench's null result in our domain (`a1`'s twin: do self-distilled skills add anything?) | Compute and report alongside `causal_lift` per curation provenance class (Phase 2) |
| P1-5 | Practice loop manual | `recertia jobs run practice` exists but nothing feeds real one-off clusters into it on a cadence | Scheduled Practice job consuming recorded one-offs; `practice_conversion` reported (Phase 2–3) |

### P2 — scale and tenant readiness (Phase 4 gate inputs)

| # | Gap | Note |
| --- | --- | --- |
| P2-1 | Postgres + pgvector soak on a real snapshot | Migration path exists by dialect swap; exercise it before any multi-tenant claim |
| P2-2 | Cross-scope promotion exercised end-to-end | `memory/scope.py` exists; needs a redaction test with a planted secret crossing scopes |
| P2-3 | Tenant quotas and per-tenant run budgets beyond the concurrency cap | API keys are scoped; quota accounting is not |
| P2-4 | Deployment topology, break-glass procedure, key rotation | Required for any unattended deploy; document before Phase 4 gate |
| P2-5 | Model-provider failover policy | Provider outage currently fails runs loud; decide whether failover to a second provider is a feature or a deliberate absence |

## 5. Threat-model deltas (since #39)

| Threat | Path | Current control | Residual |
| --- | --- | --- | --- |
| Indirect prompt injection via fetched content | `fetch` → prompt → `agent_subtask` shell | Container sandbox when enabled; fail-loud backend probe | **High** under `--local-exec`; P0-2 |
| Solver/verifier credential sharing | Same provider account for both models | `shares_identity_with` blocks identical (provider, model, credential) triples | Medium: same account, different model is permitted; a compromised account poisons both. Prefer distinct credentials in the verifier config |
| Memory poisoning via distilled content | Model-authored skills/facts re-enter context | Hygiene scan, provenance-weighted trust, review gate, adversarial tests | Medium-low: scan is signature-based; keep distiller output strictly data |
| Cost blowup through solver loop and fan-out | Loops × branches × retries | Budget accounting, divided branch budgets | **High until P0-1 lands** — the controls exist but read zero |
| Judge/model compromise | Poisoned or drifting judge inflates pass rates | Judge isolation, non-judge contribution rule | Medium until the P1-2 canary measures the false-pass rate |
| Transcript secret capture | Prompts/excerpts persisted in transcripts | Transcripts are operator-local | Low single-user; must be revisited at the tenant gate |

## 6. Residual risk statement

After the roadmap's Phase 1–2, the honest residual risks are: `a3` (no external precedent for
the tiered boundary — accepted by design, monitored via the Correction Miner's change history);
model-provider behavior drift under the harness (mitigated by recertification and the judge
canary, never eliminated); and the possibility that `a1` resolves **negative** — the treatment
arm shows no lift in our domain. That last outcome is not a failure of the system; it is the
system working as intended, and it must be publishable internally without penalty, per B7.

## 7. Non-goals for the next twelve months

1. **No weight training or online RL** (AReaL2.0's loop was deliberately rejected, ADR-0005 /
   [`references.md` §1.9](../references.md)); representational improvement only.
2. **No multi-tenant GA work** before the Phase-4 readiness gate; tenant plumbing that exists
   stays, but no new tenant surface.
3. **No third task class** before Phase 4; the second domain (`research-synthesis` fixtures
   already exist under `evals/golden/`) is the generality test, and it needs no company.
4. **No engine/framework rewrite** (ADR-0001's revisit trigger has not fired); no adoption of
   an external agent framework for the runtime.
5. **No auto-promotion past the golden gate**, regardless of how good shadow evidence gets
   (PACE **[B]**: "keep it if the score went up" is uncontrolled adaptive testing).
6. **No vendor eval platform** replacing the in-house harness; vendor tooling may supplement
   observability only.

## 8. References

Design-shaping literature is tracked in [`../references.md`](../references.md); this review
leans specifically on: Ratchet (arXiv:2605.22148 **[F]**) for lifecycle and over-pruning;
SkillsBench (arXiv:2602.12670 **[B]**) for the curation null result; Blind Curator
(arXiv:2607.07436 **[B]**) for judge false-pass risk; the Dynamic Agent Skills survey
(arXiv:2607.10113 **[F]**) for retrieval decay and missing-trajectory metrics; PACE
(arXiv:2606.08106 **[B]**) and Falsifiable Release Gates (arXiv:2607.13070 **[B]**) — both
score-9 "next reading" entries this review now promotes to design-shaping for Phases 1–2.
Operational references: OWASP Top 10 for LLM Applications (LLM01 prompt injection, LLM06
excessive agency) **[S]**; NIST AI Risk Management Framework 1.0, Govern/Map/Measure/Manage
**[S]**.
