# Narrowing the ten-year horizon to a supportable position

- **Status:** exploration instrument — not an ADR, not a remaining-work milestone
- **Date:** 2026-08-13
- **Inputs:** [`ten-year-horizon.md`](ten-year-horizon.md), [`one-year-roadmap.md`](one-year-roadmap.md),
  [`remaining-work.md`](remaining-work.md), [`../assumptions.md`](../assumptions.md),
  [`../references.md`](../references.md) §10,
  [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md)
- **Output of a successful run:** [`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md)
- **Recertia Goal:** [`ten-year-horizon-narrowing-goal.json`](ten-year-horizon-narrowing-goal.json)

The horizon is a *possibility space*. This file is the filter that turns it into a *position*
and then into a *list of objectives*. The one-year roadmap and remaining-work plan remain
the only documents that may create engineering gates. Running this instrument MUST NOT
edit those files, MUST NOT mark `a1`/`a2`/`a4` `supported`, and MUST NOT grow the graph.

## 1. Analysis: why the horizon is too wide to act on

A 10-year picture mixes five kinds of sentence that do not have the same evidential status:

| Kind | What it is | Example from the horizon | What a forecast may do with it |
| --- | --- | --- | --- |
| **Architectural fact** | Already decided, on `main` | Goal is primary input (ADR-0010); T3 is unreachable | Freeze. Not an objective to "achieve" |
| **Inherited ops / research** | Already planned; not yet evidenced | Soak weeks, probe cadence, resolve `a1` | Cite the existing `RW-*` id. Do not rewrite |
| **Interface gap** | Architecture implies it; console does not surface it; HCI literature independently requires it | T0–T3 not visible at the decision; opaque trust primary | *Candidate* objective. Independent of `a1`. UX review may rewrite `done_when` |
| **Contingent claim** | True only if a named assumption holds | Libraries replace folklore (Layer B) | Keep as objective **with the predicate attached** |
| **Speculative / market** | No Recertia evidence, no HCI requirement, no remaining-work id | Prompt engineering dies; programs replace tickets industry-wide | Drop. Record in "explicitly not objectives" |

The horizon's own §8 already forbids turning its sentences into milestones. That constraint
is load-bearing. The only *new* objectives this filter is allowed to emit are **candidates**:
interface properties the architecture already implies and the HCI record independently
asks for, which remaining-work does not yet name. Everything else is either a freeze, an
inherited `RW-*` row, or a drop.

Three further traps the filter is built to catch:

1. **Wish ≠ likely.** "Organizations compete on libraries" is a desired end-state of the
   thesis, not a base-rate forecast. SkillsBench's null on self-authored skills
   ([`references.md`](../references.md) §1.1) is the prior. Until `a1` is `supported` on
   our traffic, Layer B is a *predicate*, not a prediction.
2. **Interface gaps do not need compounding to be real.** Horvitz, Amershi, Lee & See, and
   Subramonyam et al. (horizon §4) constrain the *console* whether or not retrieval helps.
   Treating them as "Phase 4 / 2036" work is how a measurement project indefinitely
   postpones the one surface a human actually touches.
3. **The instruction gap is the residual.** Goal compilation closes the capability and
   intentionality gaps (horizon §4.2). Writing a DesiredState that is both true and
   checkable remains hard. That is the only prompt-shaped problem that survives, and it
   is an *authoring* problem (templates, a first-class precedent path — not an unmeasured
   default), not a prompting-skill problem.

**Supportable position (the filter's conclusion, restated in the objectives file):**

Recertia in the next honest slice of the future is still a Goal-compiled, retrieval-first,
T3-bounded cyclic graph with a console control plane. What will *likely* change, without
needing `a1`, is operational evidence (soak, probes, assumption intervals) and two
interface properties the architecture already implies: autonomy-tier legibility **at the
decision** (approval interstitial, not detail-only) and calibrated trust display (one
honest primary plus detail breakdown — not three numbers on every row). Goal authoring
will remain hard; the likely mitigation is task-class templates plus a first-class
retrieved-case path, not a better chat box and not an unmeasured "precedent is the
default" landing. What will *likely* change *if* `a1` is supported is Phase 3–4 of
remaining-work as already written. What is *not* supportable: that prompts, tickets, or
chat disappear as industry defaults by 2036. A UX-lead review of the first worked run
([`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md)) is an input: accepted
findings F1–F5 MUST survive a re-run.

## 2. The prompt

Copy the block below into a capable model (or into Recertia as `Goal.context`). The
machine-checkable contract is the Goal JSON, not this prose. Re-running the prompt should
regenerate [`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md), not edit
remaining-work, the roadmap, or the assumptions register, and not reverse accepted
findings in [`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md).

````markdown
You are a claims auditor, not a futurist. Your job is to narrow
`docs/architecture/ten-year-horizon.md` to a supportable position on what will
*likely* be, then emit a detailed list of objectives. You are not allowed to
invent architecture, grow the graph, or open remaining-work milestones.

# Inputs (read all of them; do not skip remaining-work)

- docs/architecture/ten-year-horizon.md
- docs/architecture/one-year-roadmap.md
- docs/architecture/remaining-work.md
- docs/assumptions.md          (status of a1, a2, a3, a4)
- docs/references.md §1 and §10
- docs/adr/0003, 0005, 0010, 0012, 0014
- docs/architecture/product-console.md (what the console already is)
- docs/architecture/ten-year-horizon-ux-review.md (accepted findings F1–F5; do not reverse)

# What "supportable" and "likely" mean here

A claim is **supportable** only if at least one of the following is true:

1. It is already an accepted ADR or shipped behaviour (architectural fact).
2. It is already a remaining-work or roadmap item with an existing id (`RW-*`,
   Phase-N gate, console C0–C4, GP0–GP2).
3. It is an interface property that (a) the architecture already implies,
   (b) remaining-work does not yet name, and (c) horizon §4 cites with [F] or
   [B] HCI evidence that does not depend on a1.
4. It is a contingent remaining-work item whose predicate (`a1` supported,
   Phase-4 gate, HEX enablement predicates) is already written down.

A claim is **likely** only if it is supportable *and* does not require a
market-wide behaviour change (jobs disappearing, tickets disappearing, chat
disappearing as a consumer default). Recertia-local interface and ops changes
can be likely. Industry-default changes cannot, on this evidence.

A claim is **not supportable** if it is a labour-market prediction, a sector
prediction, a Layer-C "programs replace tickets" picture, a graph-topology
change, HEX/auto-advance/learned-ranker enablement before predicates, or any
sentence that would mark a1/a2/a4 `supported` without real traffic.

# Method (do not skip steps; show the classification table)

1. **Inventory.** Extract every distinct claim in ten-year-horizon.md §§3–5
   and §4.8's two named gaps. One row per claim.

2. **Classify** each row as exactly one of:
   `architectural-fact` | `inherited` | `interface-gap` | `contingent` |
   `speculative` | `contradicted-by-literature`

3. **Dispose:**
   - `architectural-fact` → freeze objective (preserve; done_when is a
     regression test or a "must_not reverse" rule), or omit if already
     enforced in CI with no console/docs gap.
   - `inherited` → cite the existing `RW-*` / Phase / C* / GP* id. Do not
     rewrite the done-when. One objective per remaining-work row at most.
   - `interface-gap` → **candidate** objective. This is the only class in
     which you may mint a new `OBJ-IF-*` id.
   - `contingent` → inherit the remaining-work item and keep the predicate
     in `depends_on` and in the title. Do not drop the predicate.
   - `speculative` and `contradicted-by-literature` → "explicitly not
     objectives" list, with a one-line why.

4. **Deduplicate.** If a candidate restates remaining-work, it is inherited,
   not new. If two candidates are the same interface gap, merge them.

5. **Write the supportable position** as ≤12 sentences *before* the
   objectives list. It must distinguish unconditional / contingent-on-a1 /
   not-a-prediction. It must not introduce claims absent from the
   classification table.

6. **Emit objectives** matching the schema below. Every `done_when` must
   describe a state that can fail (a missing field, a failing test, a
   missing soak log). Soft goals ("operators feel confident") are rejected.

# Objective schema (every objective has all of these fields)

```
### OBJ-<NS>-<NAME>
- **title:**
- **kind:** inherited | candidate | freeze
- **likelihood:** unconditional | contingent-a1 | contingent-a2 | contingent-a4
- **source:** RW-* id, ADR-*, or horizon §4.x
- **why_supportable:** 2–4 sentences. Name the evidence. If inherited, say
  "already remaining-work" and stop.
- **depends_on:** none | a1.supported | a2.supported | a4.instrumented | other
- **not_established_until:** (OBJ-IF-* only) an observable on operator
  traffic, or "n/a — freeze/display rule". Citation is not validation.
- **done_when:** a checkable state. Prefer: file/field/test/ops-log exists
  and has property P. Must be fail-able.
- **must_not:** at least one concrete reversal (grow the graph, single
  quality score, mark a1 supported, edit remaining-work.md, …)
```

Namespaces: `OBJ-RW-*` inherited remaining-work, `OBJ-IF-*` interface
candidates, `OBJ-FZ-*` freezes.

# Hard limits

- Do not edit `docs/architecture/remaining-work.md`,
  `docs/architecture/one-year-roadmap.md`, `docs/assumptions.md`, or any ADR.
- Do not add HEX, auto-advance, learned rankers, a 16th graph node, or
  C5/multi-tenant chrome as objectives unless remaining-work already has
  them with their existing enablement predicate.
- Do not estimate calendar time (days, weeks, quarters, "by 2028").
- Do not use a `judge` criterion as the only success condition.
- New `OBJ-IF-*` ids: at most six. If you want more, you are minting
  product; stop and merge.
- Inherited `OBJ-RW-*` ids: at most one per remaining-work inventory row
  that is still open.
- The output file is `docs/architecture/ten-year-horizon-objectives.md`
  and only that file (plus this classification, which may live in the
  same file above the list).
- Do not restore any of: "precedent as default" / "precedent-first as the
  default Pilot path"; "three numbers on every row" / simultaneous
  calibration+resolution+specificity as the list view; "tier only on
  detail" / a detail-page badge as OBJ-IF-TIER passing. These are
  accepted findings in ten-year-horizon-ux-review.md (F1–F3).
- Do not treat the three hardcoded templates in
  `src/recertia/console_templates.py` as OBJ-IF-TEMPLATES passing (F5).
- Each OBJ-IF-* MUST include `not_established_until` (F4).

# Output shape

1. Supportable position (≤12 sentences)
2. Classification table (claim → class → disposition)
3. Objectives (schema above)
4. Explicitly not objectives (dropped speculative/contradicted claims)
5. A one-paragraph note: what would force a re-run of this prompt
   (a1/a2/a4 status change, a new [F] HCI paper that names a third
   interface gap, or an accepted UX finding this file still contradicts)

End of prompt.
````

## 3. Recertia Goal

The prompt above is `Goal.context`. The success contract is
[`ten-year-horizon-narrowing-goal.json`](ten-year-horizon-narrowing-goal.json): the
objectives file exists, contains the required headings and at least one `OBJ-IF-` candidate
and one `OBJ-RW-` inherited row, and the freeze set was not modified. Natural language
never constitutes the success contract by itself (ADR-0010).

## 4. Worked run

The prompt was applied once in-tree, then fine-tuned against
[`ten-year-horizon-ux-review.md`](ten-year-horizon-ux-review.md). Result:
[`ten-year-horizon-objectives.md`](ten-year-horizon-objectives.md). Re-running it is
allowed; editing remaining-work as a side effect of a re-run is not; reversing
accepted UX findings F1–F5 is not.
