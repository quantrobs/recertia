# UI/UX-lead review of the ten-year horizon plan

- **Status:** exploration review — **not an engineering gate**, not remaining-work
- **Date:** 2026-08-13
- **Reviewer role:** UI/UX lead (named design critique). This repo has no designated UX
  owner; the review is not a persona co-sign.
- **Inputs:** [`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md) (pre-rewrite),
  [`ten-year-horizon.md`](ten-year-horizon.md) §4, [`product-console.md`](product-console.md),
  [`../specifications/product-console.md`](../specifications/product-console.md),
  [`../references.md`](../references.md) §10, shipped Compose / templates / skills /
  proposal-decision code
- **Outcome applied in:** rewritten `OBJ-IF-*` blocks in
  [`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md)
- **Must not:** edit [`remaining-work.md`](remaining-work.md),
  [`one-year-roadmap.md`](one-year-roadmap.md), [`../assumptions.md`](../assumptions.md),
  or any ADR; mint a fifth `OBJ-IF-*`; promote any candidate into remaining-work

This is the same genre as the archived
[principal architecture review](../archive/2026-Q3/principal-review-2026-08.md): a
falsifiable critique of a plan, not an implementation. It walks the *shipped* console so
the findings are not literature-only.

## Verdict

Agree with the *substance* of the four interface candidates (`OBJ-IF-TIER`,
`OBJ-IF-TRUST`, `OBJ-IF-PRECEDENT`, `OBJ-IF-TEMPLATES`). Reject three of their original
`done_when` clauses. Do not promote any of them into remaining-work.

HCI citations in horizon §4 and [`references.md`](../references.md) §10 constrain the
console whether or not `a1` compounds. They do **not** validate a design. By this
project's own B7 standard, literature is a prior, not a pass.

| Objective | Verdict | Why |
| --- | --- | --- |
| `OBJ-IF-TIER` | agree-with-rewrite | Tier must be legible at the **decision**, not only on a detail page |
| `OBJ-IF-TRUST` | agree-with-rewrite | Lee & See is calibration, not "always render three numbers" |
| `OBJ-IF-PRECEDENT` | agree-with-rewrite | Retrieval-first is supported; **defaulting** it is anchoring, unmeasured |
| `OBJ-IF-TEMPLATES` | agree-with-rewrite | Templates already ship; the gap is a versioned linted library |
| `OBJ-FZ-GRAPHVIEW` | agree | Keep run detail graph-shaped; chat stays a composition surface |
| `OBJ-FZ-CONTEXT` | agree | `Goal.context` is secondary notation; do not compile it |
| `OBJ-FZ-TOPOLOGY` / `OBJ-FZ-B7` | agree | Out of UX scope; do not reverse |
| `OBJ-RW-*` | agree (no UX rewrite) | Inherited ops/research; this review does not restaff them |

## Shipped console (what the plan was scored against)

C0–C4 already exist. The candidates overstate some gaps and understate others.

| Surface | Where it lives | What a UX lead actually sees |
| --- | --- | --- |
| Pilot Compose / Suggest | `src/recertia/console_compose.py`, `POST /v1/goals/suggest` | Drafts from heuristic / model / template. Drafts never lock. Blank Goal form is still the natural landing. |
| Templates | `src/recertia/console_templates.py`, `GET /v1/templates` | Three hardcoded `repo-chore` skeletons (`add-gitignore-pyc`, `add-editorconfig`, `add-pytest-config`) in a module dict — not a versioned, linted library. |
| Skill list contribution | `GET /v1/skills` returns `contribution` | A contribution object is already in the list payload. Display calibration (interval vs point estimate vs `"not established"`) is unspecified. The failure mode is **how** the number is shown, not a missing field. |
| T2 enforcement | `POST /v1/proposals/{id}/decision` in `console_routes.py` | T2 / `correction` requires `reviewer` or admin. The 403 is `"T2 requires reviewer"`. No operator-language *why*, no tier sentence in an approval interstitial. Enforcement without explanation. |
| Run detail | [`product-console.md`](product-console.md) §3.1 | Route log, spend, manifest, failure class — already graph-shaped. |
| Proposal inbox | spec §3.3, architecture §3.2 | Approve / reject / request-changes. Kind and payload `tier` exist; they are not presented as a user-legible autonomy property at click time. |

## Findings

### F1 — Trust display: calibration, not width — `accepted`

**Claim under test:** `OBJ-IF-TRUST` as originally written required skill show / Tower to
render calibration, resolution, *and* specificity as co-equal figures, and treated "never
one number" as a simultaneous-display rule ([`ten-year-horizon.md`](ten-year-horizon.md)
§4.4).

**Why it fails as a UX requirement.** Lee & See (2004) **[F]** name three *properties of
trust* an interface must support — calibration, resolution, specificity — not three
widgets that must occupy every row. Amershi et al. (2019) **[F]** G2 / transparency
overload: showing three metrics everywhere buries the one that matters and trains
operators to ignore the panel. List views of skills need a scannable primary. The real
failure mode is an **opaque** or **uncalibrated** primary (a star, a rounded point
estimate whose interval spans zero, a composite that hides `"not established"`), not
the existence of a primary.

**Disposition.** Rewrite `done_when` as progressive disclosure: one honestly calibrated
primary on list/summary (must render `"not established"` when the interval spans zero);
calibration, resolution, and specificity on detail. `must_not` still forbids a composite
that hides `"not established"`; it also forbids requiring three numbers on every list
row.

### F2 — Precedent-as-default is anchoring, asserted not measured — `accepted`

**Claim under test:** `OBJ-IF-PRECEDENT` made retrieved-case edit *the default* Pilot
authoring path, with the blank form as an escape hatch.

**Why it fails as a UX requirement.** Zamfirescu-Pereira et al. (2023) **[B]**,
Subramonyam et al. (2024) **[F]**, and Cypher et al. (1993) **[F]** support
retrieval/example against a blank page. They do not license *defaulting every author*
into the nearest past Goal. That is the estimation-anchoring failure: the retrieved case
suppresses articulation of what is actually different. Compose/Suggest already exists;
making it the landing state is a bigger interaction change than the original objective
treated it as, and it was closed by citation rather than by a metric. That is
inconsistent with B7 (this project will not mark `a1` `supported` from literature).

Templates already cover three golden-shaped chores. Fighting templates and precedent
for the same landing state is a product expansion. Known task class → template; no
template → precedent as a reachable path. Default-vs-blank is a measured decision.

**Disposition.** Title and `done_when` become: first-class retrieved-case path, **not**
the default. Blank form remains. Default-vs-blank does **not** pass this objective.
`not_established_until` names time-to-lock, criteria-rework rate, or blank-form escape
rate on real Pilot traffic.

### F3 — Tier legibility belongs at the decision — `accepted`

**Claim under test:** `OBJ-IF-TIER` was satisfied by showing T0–T3 on run detail and
skill detail (CLI `skills show` and/or Tower).

**Why it fails as a UX requirement.** Norman's gulf of evaluation (Hutchins, Hollan &
Norman 1985 **[F]**; horizon §4.1) is about feedback at the moment of the judgement, not
in a page the operator has to remember to open. Horvitz (1999) **[F]** and the 2025
levels-of-autonomy note **[F]** treat autonomy as a *user-legible role at the act*. T2
is already enforced at `POST /v1/proposals/{id}/decision`; a detail-page badge can pass
the original `done_when` while every approval click still looks like an undifferentiated
"approve."

**Disposition.** `done_when`: T2 (and any human-gated action) shows the applicable tier
plus one operator-language *why* **in the approval interstitial**. Run/skill detail may
repeat it. A detail-only badge **fails** this objective. `must_not` unchanged (no
solver-requested slider, no graph growth).

### F4 — Interface hypotheses get B7 treatment — `accepted`

**Claim under test:** the four `OBJ-IF-*` rows were "supportable" because architecture
implies them and HCI independently requires them. Supportable ≠ validated.

**Why it fails as an epistemic requirement.** `docs/assumptions.md` will not mark `a1`
`supported` from SkillsBench or Ratchet — only from measured traffic. These four
objectives were derived the same way (literature plus architectural inference) with no
operator having used a tier interstitial, a calibrated trust primary, a precedent path,
or a linted template library. Calling them "candidate" understates that they are
hypotheses.

**Disposition.** Each `OBJ-IF-*` carries `not_established_until` with an observable on
operator traffic, or `n/a` when the row is a display/freeze rule rather than a behaviour
change. Status stays untested until observed. Do **not** mint `a*` ids — assumptions.md
is frozen. Citation is not validation.

### F5 — Scope candidates to the real gap — `accepted`

**Claim under test:** `OBJ-IF-TEMPLATES` (and, in passing, PRECEDENT and TRUST) read as
if the console lacked templates, suggestion, and contribution.

**Why it fails as scoping.** Three templates, Suggest, and a contribution object already
ship (table above). Inventing those surfaces again would duplicate C0–C4. The remaining
gaps are: templates are a hardcoded `TEMPLATES` dict, not a reviewed versioned library
with a lint equivalent to `recertia skills lint`; Suggest is not a retrieve-similar-Goal
path; contribution is an API field whose display calibration is unspecified.

**Disposition.** `OBJ-IF-TEMPLATES` `done_when` stays about reviewed Goal skeletons per
golden task class, a lint, and versioned artifacts. `must_not` adds: do not treat the
three existing hardcoded templates as this objective passing. PRECEDENT and TRUST
rewrites (F1, F2) already stop inventing Compose and inventing a contribution field.

## Explicitly not accepted

| Proposal | Why deferred / rejected |
| --- | --- |
| Promote any `OBJ-IF-*` into [`remaining-work.md`](remaining-work.md) | Separate, explicit decision. This review is not that decision. |
| Mint `a5`… for interface hypotheses | assumptions.md is frozen; `not_established_until` is enough |
| Locked-Goal amend-in-place / viscosity "like git" | Still dropped until a lock-preserving design exists (objectives §4) |
| Fifth `OBJ-IF-*` (gentle-slope curator, C5 chrome, …) | Product expansion; narrowing cap is six and four is enough |
| Usability-study instrumentation beyond naming the metrics | Next step, after the rewritten `done_when` exists |
| Console implementation in this change | Out of scope. The review exists to stop building the *wrong* `done_when`. |

## What this review does to the plan

Accepted findings F1–F5 are applied in
[`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md) (supportable position,
classification wording, four `OBJ-IF-*` blocks).
[`ten-year-horizon-narrowing.md`](ten-year-horizon-narrowing.md) is patched so a re-run
cannot restore "precedent as default", "three numbers on every row", or "tier only on
detail". Horizon §4.4 / §4.8 keep the house rule against an **opaque** single score and
state progressive disclosure.

No remaining-work, roadmap, assumptions, or ADR file is edited.
