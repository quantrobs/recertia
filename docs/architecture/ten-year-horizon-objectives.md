# Ten-year horizon — supportable position and objectives

- **Status:** exploration output — **not an engineering gate**, not remaining-work
- **Date:** 2026-08-13
- **Produced by:** one application of [`ten-year-horizon-narrowing.md`](ten-year-horizon-narrowing.md) §2
- **UX review:** [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) (F1–F5 applied)
- **Goal:** [`ten-year-horizon-narrowing-goal.json`](ten-year-horizon-narrowing-goal.json)

Re-running the narrowing prompt may replace this file. It MUST NOT edit
[`remaining-work.md`](remaining-work.md), [`one-year-roadmap.md`](one-year-roadmap.md),
[`../assumptions.md`](../assumptions.md), or any ADR. A re-run MUST keep the
UX-accepted constraints in [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md):
no "precedent as default", no "three numbers on every row", no "tier only on detail".

## 1. Supportable position

Recertia, unconditionally, remains what it already is: a Goal-compiled, retrieval-first,
T3-bounded cyclic graph with a console control plane. That is architecture, not a forecast.

What will *likely* change without needing `a1` is evidence, not shape: operator-mode GA
closeout (soak, tabletop, cost), live probe cadence, and honest intervals on `a1` / `a2` /
`a4` — including the honest result `"not established"`. Independently of whether memory
compounds, two interface properties the architecture already implies and the HCI record
independently requires will likely need to be *surfaced*: autonomy-tier legibility at the
decision (T0–T3 readable in the T2 approval interstitial, not only in ADRs or on a detail
page) and calibrated trust display (one honest primary that may read `"not established"`,
with calibration, resolution, and specificity on detail — never an opaque composite).
Goal authoring will remain the residual hard problem (the instruction gap); the likely
mitigation is task-class DesiredState templates plus a first-class retrieved-case path,
not a better prompt box and not an unmeasured "precedent is the default" landing. These
four interface properties remain untested until observed; citation is not validation.

What will *likely* change *if* `a1` is `supported` on real `repo-chore` traffic is Phase 3–4
of remaining-work as already written: curator-from-replay, composition on live traffic, a
second domain on the unchanged runtime, and a multi-tenant decision made by criteria fixed
in advance. If `a1` is `refuted`, Layer B and Layer C die and the product that remains is a
competent Goal-gated agent with no compounding thesis.

What is *not* a supportable prediction: that prompt engineering, tickets, or chat disappear
as industry defaults by 2036; that programs replace tickets outside Recertia; that the
graph grows; that HEX, auto-advance, or learned rankers enable themselves.

## 2. Classification table

| Horizon claim | Class | Disposition |
| --- | --- | --- |
| Work is issued as a Goal / desired state | architectural-fact | Freeze ADR-0010; no new objective |
| Chat remains, off the critical path (Recertia) | architectural-fact | Freeze ADR-0012 Pilot/Tower split |
| Chat / prompts die as industry defaults | speculative | Drop (§4) |
| Competence lives in libraries, not weights | contingent | Inherit Phase 2–3 (`RW-A`, `RW-LY`) with `depends_on: a1` |
| Humans curate contracts and T2/T3 gates | architectural-fact | Freeze ADR-0005; inherit review/curator rows |
| The cyclic graph does not go away | architectural-fact | `OBJ-FZ-TOPOLOGY` |
| Measurement honesty / causal lift | inherited | `OBJ-RW-M2`, `OBJ-RW-A1` |
| T3 line holds | architectural-fact + `a3` untested | `OBJ-FZ-T3`; `a3` stays research |
| Models become interchangeable solvers | architectural-fact locally; speculative as market | Freeze run-manifest pinning; drop market claim |
| Layer A — contracts replace prompts | inherited | `OBJ-RW-GA` and console C0–C4 (shipped) |
| Layer B — libraries replace folklore | contingent | Inherit Phase 3–4; predicate `a1.supported` |
| Layer C — programs replace tickets | speculative | Drop (§4) |
| T0–T3 enforced but not console-legible at the decision (§4.3, §4.8) | interface-gap | `OBJ-IF-TIER` (approval interstitial; detail-only fails) |
| Trust display collapses to one opaque number (§4.4, §4.8) | interface-gap | `OBJ-IF-TRUST` (calibrated primary + detail breakdown) |
| Instruction gap survives (§4.2) | interface-gap | `OBJ-IF-PRECEDENT` (first-class, not default), `OBJ-IF-TEMPLATES` (versioned library) |
| Tower/run view flattened back to chat (§4.5) | interface-gap / freeze | `OBJ-FZ-GRAPHVIEW` |
| `Goal.context` squeezed out as legacy (§4.6 secondary notation) | interface-gap / freeze | `OBJ-FZ-CONTEXT` |
| Locked-Goal viscosity / amend-in-place (§4.6) | speculative-as-objective | Drop until a lock-preserving design exists (§4) |
| Gentle slope user→curator (§4.7) | inherited-in-part | Covered by Phase-3 Correction Miner; no extra id |
| Prompt engineering as a job is gone | speculative | Drop (§4) |
| Mega-Goals / prompt-only packs | architectural-fact (already rejected) | Freeze ADR-0014 |
| Unbounded autonomy as a feature | contradicted-by-literature + ADR-0005 | Freeze; drop as a "will happen" claim |

## 3. Objectives

Candidate `OBJ-IF-*` rows are **not** remaining-work. Promoting any of them into
[`remaining-work.md`](remaining-work.md) is a separate, explicit decision. Each
`OBJ-IF-*` carries `not_established_until`: literature support is a prior, not a pass
([`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F4).

### OBJ-RW-GA

- **title:** Close operator-mode GA on shipped code
- **kind:** inherited
- **likelihood:** unconditional
- **source:** `RW-GA` in remaining-work; one-year roadmap Phase 1
- **why_supportable:** Already remaining-work. Code exists; ops cadence does not. This is
  the minimum product that can generate truthful traffic for `a1`.
- **depends_on:** none
- **done_when:** Four consecutive weekly soak runs of the golden suite complete without
  manual intervention; a completed tabletop (or live incident) log exists and is linked
  from a run id; baseline `cost_per_solved_task` is a number on real operator traffic.
- **must_not:** Treat "tooling shipped" as GA; skip soak because the horizon sounds larger.

### OBJ-RW-M2

- **title:** Run probe + golden + ablation cadence on live traffic
- **kind:** inherited
- **likelihood:** unconditional
- **source:** `RW-M2`; one-year roadmap Phase 2
- **why_supportable:** Already remaining-work. Engineering for `MetricReport` is shipped;
  the live eval DB and schedule are ops.
- **depends_on:** none (harness exists)
- **done_when:** A weekly lift report is produced from live `repo-chore` probes with the
  ablation arm at the governed rate, and reports `"not established"` whenever the interval
  spans zero.
- **must_not:** Fill the interval by suppressing the control arm; treat synthetic fixtures
  as a1 evidence.

### OBJ-RW-A1

- **title:** Resolve `a1` with a stated interval (either direction)
- **kind:** inherited
- **likelihood:** unconditional (the *resolution* is unconditional; a positive result is not)
- **source:** `RW-A`; [`assumptions.md`](../assumptions.md) `a1`
- **why_supportable:** Already remaining-work / B7. The claim is whether machine-checkable
  `repo-chore` shows causal lift from retrieval. Status today: `under evaluation`.
- **depends_on:** `OBJ-RW-M2` traffic
- **done_when:** `docs/assumptions.md` `a1` status is `supported` or `refuted` with a
  Wilson interval from real traffic, in a commit, not a conversation. `"not established"`
  remaining after a stated accumulation window is an allowed, recorded outcome — it is
  not this objective passing.
- **must_not:** Mark `supported` from literature (Ratchet, SkillsBench) or from synthetic
  nulls; make a positive `a1` a merge requirement.

### OBJ-RW-A2

- **title:** Resolve `a2` — evidence-floor reachability at our volume
- **kind:** inherited
- **likelihood:** unconditional (resolution); floor-cleared is contingent
- **source:** `RW-A`; assumptions `a2`
- **why_supportable:** Already remaining-work. Ratchet's floor is a design parameter; whether
  most skills ever clear it is an empirical question, including a useful negative.
- **depends_on:** live + Practice trial volume
- **done_when:** `a2` is `supported` or `refuted` with observed certification-trial
  accumulation rates per skill (real + Practice), committed to `assumptions.md`.
- **must_not:** Lower `evidence_floor` to make the claim true; count Practice trials as
  user-facing lift.

### OBJ-RW-A4

- **title:** Instrument `a4` — judge false-pass canary on live verifier versions
- **kind:** inherited
- **likelihood:** unconditional
- **source:** `RW-A`; assumptions `a4`; horizon §3.6
- **why_supportable:** Already remaining-work. Blind Curator: false-pass bias silently
  disables retirement. Isolation is necessary and shipped; a measured rate is not.
- **depends_on:** none (canary fixtures exist)
- **done_when:** False-pass rate is reported per provider × model version on the real
  canary schedule; `a4` moves from `untested` to `under evaluation` at minimum.
- **must_not:** Ask the solver whether it agrees with the judge; skip the canary after a
  model upgrade.

### OBJ-RW-P4

- **title:** Keep the Phase-4 multi-tenant gate criteria fixed before the evidence arrives
- **kind:** inherited
- **likelihood:** contingent-a1 (the *go* decision); writing the criteria is unconditional
  and already done
- **source:** remaining-work `RW-C5` / `RW-TM`; one-year roadmap Phase 4; production-readiness.md
- **why_supportable:** Already remaining-work. The gate (operator GA for a full phase; `a1`
  supported in at least one domain; P2 closed; signed threat model) is the B7 machinery
  that stops a null-lift system from multiplying blast radius.
- **depends_on:** `a1.supported` for a *go*; none for keeping the written criteria
- **done_when:** A go/defer decision exists that cites the pre-written criteria; a defer
  because `a1` is not `supported` counts as this objective passing.
- **must_not:** Relax the gate because Layer C sounds attractive; ship C5 before the gate.

### OBJ-IF-TIER

- **title:** Make T0–T3 autonomy legible at the decision, not only on a detail page
- **kind:** candidate
- **likelihood:** unconditional
- **source:** horizon §4.3, §4.8; ADR-0005; Horvitz 1999 **[F]**; Amershi et al. 2019 **[F]**;
  Levels of Autonomy for AI Agents, arXiv:2506.12469 **[F]**;
  [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F3
- **why_supportable:** T0–T3 is already enforced (`POST /v1/proposals/{id}/decision`
  403s T2 without reviewer). Mixed-initiative HCI treats autonomy as a *user-legible*
  property at the act, orthogonal to model capability. Norman's gulf of evaluation is
  at the decision, not on a page the operator must remember to open. Independent of `a1`.
- **depends_on:** none
- **not_established_until:** an operator (or fixture acting as one) completes a T2
  approve/reject from the interstitial copy, not from a detail-page badge alone
- **done_when:** T2 and any other human-gated action show the applicable tier plus one
  operator-language sentence of *why* **in the approval interstitial** (e.g. "T2:
  retrieval-threshold change, human approval required"; "T3: sandbox policy, not
  reachable from this action"). Run detail and skill detail MAY repeat the same
  sentence. A detail-only badge **fails** this objective. Existing T3 unreachability
  tests still pass.
- **must_not:** Let a run or job *change* its own tier; collapse T0–T3 into a single
  "autonomy slider" the solver can request; grow the graph to display this; treat a
  run/skill-detail badge as this objective passing.

### OBJ-IF-TRUST

- **title:** Calibrated primary on lists; calibration, resolution, specificity on detail
- **kind:** candidate
- **likelihood:** unconditional
- **source:** horizon §4.4, §4.8; Lee & See 2004 **[F]**; Amershi et al. 2019 **[F]**;
  measurement-integrity.md; [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F1
- **why_supportable:** Contribution scores, Wilson intervals, and `"not established"`
  already exist in the metrics pipeline (`GET /v1/skills` already returns
  `contribution`). The gap is display calibration, not a missing field. Lee & See
  constrain trust *properties*; they do not require three widgets on every row.
  Independent of `a1`.
- **depends_on:** none (numbers may honestly be `unavailable`)
- **not_established_until:** a list-view fixture whose interval spans zero leads with
  `"not established"` (not a rounded point estimate), and a detail view of the same
  skill discloses calibration, resolution, and specificity
- **done_when:** Skill list / summary shows **one** honestly calibrated primary:
  contribution or lift with interval, or `"not established"` when the interval spans
  zero, or an `unavailable` reason — never a star, percentage, or rounded point
  estimate as the lead. Skill show / Tower skill **detail** discloses (1) that same
  calibrated primary, (2) a probe-level win/loss or selected-vs-suppressed split when
  observations exist (resolution), (3) a breakdown by task class and/or model id
  (specificity). `"not established"` is the list primary whenever the interval spans
  zero.
- **must_not:** Invent a composite score that hides `"not established"`; show one
  library-wide rating; require three numbers on every list row; treat this as a reason
  to change contribution math.

### OBJ-IF-PRECEDENT

- **title:** Offer retrieved-case edit as a first-class Goal-authoring path in Pilot
- **kind:** candidate
- **likelihood:** unconditional
- **source:** horizon §4.2, §4.6; Zamfirescu-Pereira et al. 2023 **[B]**; Subramonyam et
  al. 2024 **[F]**; Cypher et al. 1993 **[F]**;
  [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F2
- **why_supportable:** Compilation already closes capability and intentionality gaps.
  The surviving instruction gap is authoring a DesiredState. HCI supports
  retrieval/example against a blank page; it does not license defaulting every author
  into the nearest past Goal (anchoring). Suggest/Compose already exist; the gap is a
  retrieve-similar-Goal path, not inventing Compose. Independent of `a1`.
- **depends_on:** none
- **not_established_until:** time-to-lock, criteria-rework rate, or blank-form escape
  rate is observed on real Pilot traffic. Literature citations do not close this.
  Default-vs-blank is not this objective passing.
- **done_when:** Pilot Compose exposes retrieve similar Goals/cases → present a
  diffable draft → human edits → preview `compile_goal` → submit as a reachable
  first-class control (not buried behind Suggest-only heuristics). A blank Goal form
  remains. When a golden task class has a reviewed template, that template is the
  suggested start; the precedent path is for "no template matches." Drafts still
  never lock (ADR-0003). Making precedent the landing state is **not** this
  objective passing.
- **must_not:** Auto-lock a suggested Goal; skip `compile_goal` preview; replace
  DesiredState fields with a prompt box; make retrieved-case edit the default Pilot
  path without the `not_established_until` measurement.

### OBJ-IF-TEMPLATES

- **title:** Versioned DesiredState templates per golden task class
- **kind:** candidate
- **likelihood:** unconditional
- **source:** horizon §4.2; ADR-0010 "task-class templates"; product-console.md Pilot templates;
  [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) F5
- **why_supportable:** Three hardcoded templates already ship
  (`src/recertia/console_templates.py`: gitignore, EditorConfig, pytest.ini). The
  instruction-gap mitigation is a *reviewed, versioned, linted* library per golden
  task class, the same way skills are reviewed — not inventing templates. Independent
  of `a1`.
- **depends_on:** none
- **not_established_until:** an operator authors a new golden-class Goal from a
  reviewed template that is not one of the three hardcoded dict entries, and
  `compile_goal` plus the template lint both pass
- **done_when:** Each golden task class under `evals/golden/` has at least one reviewed
  Goal template (DesiredState + Constraint skeletons) that `compile_goal` accepts; a
  lint equivalent to `recertia skills lint` exists for templates; templates are
  versioned artifacts (not only SPA / `TEMPLATES` dict hardcoding).
- **must_not:** Treat templates as executable skills; silently mutate a locked run's
  criteria from a template update; add judge-only templates; treat the three existing
  hardcoded templates as this objective passing.

### OBJ-FZ-GRAPHVIEW

- **title:** Keep the run view graph-shaped
- **kind:** freeze
- **likelihood:** unconditional
- **source:** horizon §4.5; ADR-0001; ADR-0012 Tower/run detail
- **why_supportable:** Graphologue and Sensecape retrofit structure onto linear chat.
  Recertia's route log *is* that structure. Flattening it "for familiarity" spends the
  advantage. This is a preservation rule, not a build.
- **depends_on:** none
- **done_when:** Run detail's primary view remains route log / graph / spend / manifest
  (product-console.md §3.1). A review comment that proposes a chat-shaped *primary* run
  view is a recorded design finding; chat remains allowed as a composition surface
  (Pilot Compose), not as the execution record.
- **must_not:** Make a transcript-replay chat the default run detail; hide join-accounting
  or missing-branch failures behind prose.

### OBJ-FZ-CONTEXT

- **title:** Keep `Goal.context` / `Task.request` as non-executable secondary notation
- **kind:** freeze
- **likelihood:** unconditional
- **source:** horizon §4.6; ADR-0010; Green & Petre 1996 **[F]**
- **why_supportable:** Closeness of mapping and secondary notation are why DesiredStates
  stay readable English and why "why" must not be compiled. Squeezing `context` out as
  legacy recreates opaque-syntax prompts.
- **depends_on:** none
- **done_when:** `contracts/goal.py` still has a non-compiled `context` field;
  `compile_goal` still ignores it for criteria; at least one golden Goal fixture still
  carries context without that context appearing in locked `TaskCriterion[]`.
- **must_not:** Compile `context` into criteria; delete the field as "legacy"; require
  context to be empty for new clients.

### OBJ-FZ-TOPOLOGY

- **title:** Fifteen graph nodes remain T3
- **kind:** freeze
- **likelihood:** unconditional
- **source:** remaining-work §1 rule 3; ADR-0001; ADR-0005
- **why_supportable:** Already remaining-work / T3. The horizon explicitly must not grow
  the graph. HEX, compress, learned rankers, auto-advance stay behind existing
  enablement predicates.
- **depends_on:** none
- **done_when:** Existing topology/T3 tests still pass; no objective in this file
  proposes a 16th node.
- **must_not:** Add a node to "make the forecast real"; enable HEX before
  `practice_conversion` and a weekly lift interval are numbers.

### OBJ-FZ-B7

- **title:** Do not promote research outcomes into merge requirements
- **kind:** freeze
- **likelihood:** unconditional
- **source:** assumptions.md B7; remaining-work §1 rule 1; horizon §8
- **why_supportable:** The entire measurement thesis. This file exists because the
  horizon was too easy to misread as a plan.
- **depends_on:** none
- **done_when:** No `done_when` in this file requires `a1`/`a2`/`a4` to be `supported`
  in order to merge unrelated code; `OBJ-RW-A1`/`A2`/`A4` remain research outcomes.
- **must_not:** Use this objectives list as a staffing plan or as a reason to open a
  remaining-work milestone without a separate decision.

## 4. Explicitly not objectives

| Dropped claim | Why |
| --- | --- |
| Prompt engineering as a profession is gone | Labour-market prediction; no Recertia evidence. The instruction gap *survives* as authoring |
| Chat disappears | Contradicted by the horizon's own §3.2; chat stays as composition/debug |
| Programs replace tickets industry-wide (Layer C) | Sector prediction. Goal packs exist *inside* Recertia (GP0–GP2); that does not license a 2036 market claim |
| Organizations compete on libraries the way they competed on codebases | Desired thesis end-state; prior is SkillsBench null until `a1` is `supported` |
| Locked-Goal amend/viscosity "like git" | Would weaken ADR-0003 unless a lock-preserving design is written first; not supportable as an objective today |
| HEX / `curator_compress` / learned rankers / auto-advance / 16th node | Remaining-work already gates these; the horizon is forbidden from enabling them |
| Multi-tenant console chrome (C5) as an unconditional objective | Already `RW-C5`, Phase-4 gated; duplicating it without the predicate is how blast radius multiplies |
| A no-memory general agent "will not win" | That is falsification clause 4 of the horizon, not a build objective |
| Gentle-slope "everyone is a curator" product | Partial inherit of Phase-3 Correction Miner; minting a new id is product expansion |

## 5. When to re-run the prompt

Re-run [`ten-year-horizon-narrowing.md`](ten-year-horizon-narrowing.md) §2 when, and only
when:

- `a1`, `a2`, or `a4` changes status in `docs/assumptions.md`, or
- a new **[F]** HCI paper names a third interface gap that is not already `OBJ-IF-TIER`,
  `OBJ-IF-TRUST`, `OBJ-IF-PRECEDENT`, or `OBJ-IF-TEMPLATES`, or
- [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md) marks a finding
  `accepted` that this file still contradicts.

A re-run that wants more than six `OBJ-IF-*` ids is minting product; stop. A re-run
MUST NOT restore "precedent as default", "three numbers on every row", or "tier only
on detail".
