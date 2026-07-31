# Fandea Architecture: 8. Improvement plane

## 8. Improvement plane

Five scheduled jobs. Each proposes changes through the same review and promotion path as any
run — no job writes `approved` state directly. See
[ADR-0004](../adr/0004-offline-improvement-plane.md).

### 8.1 Miner — cold-start bootstrap

An empty library means every early user pays full price and the system looks worse than a
plain agent exactly when first impressions form. The Miner attacks that by distilling
candidate skills and facts from artefacts that already exist: git history, merged pull
requests, CI configuration, runbooks, and docs. Mined candidates enter as `draft` and must
pass validation like anything else — but they arrive with real evidence attached, because a
merged PR is a solved task with a review already on it.

This job is more than a convenience. Mined skills are `mined_from_human_artifact`, and the
measured gap between human-curated and self-generated skills
([`references.md`](../references.md) §1.1) makes human-authored history the single most promising
source of early library quality. If that gap replicates in our domain, the Miner is the primary
mechanism and self-distillation is the supplement — the reverse of the original assumption.

### 8.2 Curator — capacity and entropy control

Retrieval precision decays as a library grows, and the surveyed literature puts that decay in the
moderate regime of tens to hundreds of skills, with lifecycle management "largely neglected" as
the field-wide bottleneck ([`references.md`](../references.md) §1.1, §1.5). Curation is therefore the
load-bearing subsystem, not housekeeping.

The Curator proposes, in rough order of measured value: **retiring** skills with negative
contribution past the evidence floor (§7.2), **extracting** shared sub-procedures into child
skills (§6), **splitting** overloaded skills whose criteria fail in uncorrelated clusters,
**tightening** preconditions that produced wrong retrievals, **merging** near-duplicates, and
**compacting** version chains. Every proposal is a diff, gated by the golden-set regression run.

Two proposals act on step graphs rather than skill content. **Parallelise** removes an
`input_bindings` entry whose bound input was unused across repeated runs — and whose steps'
claims do not overlap. **Serialise** does the reverse, adding a binding or widening a claim
after repeated merge failures or resource conflicts on the same wave. This is the loop that
makes concurrency a learned property: the distiller writes bindings from a single transcript,
and the Curator relaxes or tightens them once many runs have shown which consumptions were real.

Deduplication sits late in that list deliberately: with a consistent authoring prior in place,
explicit deduplication was found to be largely subsumed by the prior itself
([`references.md`](../references.md) §1.2), so it earns effort only after retirement and abstraction
are working.

### 8.3 Practice — curriculum at the frontier

Waiting for user tasks means learning only what traffic happens to cover. Practice generates
tasks aimed at the frontier of competence: task classes with high failure rates, classes with
≥3 recorded one-offs, skills with stale certification, and near-miss variations of tasks that
just barely passed. Selection targets the band where success probability is neither near 1
nor near 0, because that is where an attempt carries information. Practice runs are marked as
such, are budgeted separately, and their results never count toward user-facing metrics.

### 8.4 Recertifier — drift defence

Skills rot without anyone touching them: tools upgrade, APIs change, the model version
changes underneath. The Recertifier re-runs skills against their golden fixtures on a
schedule and on triggers — model upgrade, tool version change, child invalidation — and moves
failures to `needs_recert` or `quarantined` (§13).

### 8.5 Correction miner — improving the learner

When a reviewer edits a draft before approving, the diff is the single highest-quality signal
the system receives: a human demonstrating what a good skill looks like. The original design
stored the decision and discarded the edit. The Correction miner clusters these diffs into
recurring correction patterns and proposes updates to distiller guidance and criteria
templates. This is where the system improves *how it learns*, not just what it knows — and it
is bounded by §14.
