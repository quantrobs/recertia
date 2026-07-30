# ADR-0006: Bounded active library with contribution-score retirement

- **Status:** accepted
- **Evidence base:** [`../references.md`](../references.md) §1.1, §1.2, §1.6, §1.8

## Context

The design assumed that a growing, curated library monotonically improves retrieval and
therefore performance. Two empirical results contradict parts of that assumption.

**Self-authored skills showed no measured benefit.** SkillsBench (arXiv:2602.12670, 2026) reports
human-curated skills at +16.2pp over a no-skill baseline while LLM-self-generated skills deliver
+0.0pp. Ratchet (arXiv:2605.22148, 2026) reframes this: holding the author fixed and improving
only lifecycle management yields +0.328 rolling-mean gain on MBPP+ hard-100 where an unmanaged
library drifts at +0.002. The bottleneck is the librarian, not the author — and our design had a
Curator but no capacity bound and no outcome-driven retirement, which is precisely the unmanaged
configuration that drifts.

**Unbounded growth removes any performance floor.** Ratchet's Proposition 1 gives a
non-divergence bound — expected pass rate cannot fall below `E[p0] − (τ + ε) − Cδ` — that holds
only when the active cap `C` and retirement threshold `τ` are finite. With unbounded `C` and no
`τ`, "the bound collapses."

**But pruning aggressively is worse than not pruning.** Their harsh-retirement ablation
(evidence floor 20 trials, threshold 0) lands at −0.019, *below* the no-skill floor. Our
`min_trust = 0.4` filter applied after only 3 applications was exactly this setting.

## Decision

1. **Bounded active set.** Only `active` skills are retrievable. `active_cap` (default 50 per
   task class) bounds the active set, so skills compete for retrievable slots rather than
   accumulating.
2. **Contribution-score retirement with an evidence floor.** Retire (bench) a skill when it has
   at least `evidence_floor` applications (default 30) **and** its estimated contribution
   `ĉ(s) ≤ −retirement_threshold` (default 0.10). Contribution is estimated against the ablation
   control arm's baseline for the task class, which the design already collects, and is scored
   from required non-`judge` criteria only — a false-pass-biased model judge silently disables
   retirement otherwise ([`references.md`](../references.md) §1.8).
3. **`benched` is reversible and non-destructive.** A benched skill is retained with full history
   and may return to `active` if evidence changes or the Curator revises it. Benching is not
   deprecation and not quarantine.
4. **Low evidence means demote, never drop.** Skills below the evidence floor are score-demoted
   in ranking but not retired, replacing the previous hard `min_trust` cut.
5. **Finiteness is structural.** Specific values of `active_cap`, `retirement_threshold`, and
   `evidence_floor` are tunable (T2); the requirement that cap and threshold be *finite* is T3,
   since the floor property depends on it.
6. **Curation provenance is recorded and used.** Skills carry `curation`:
   `human_authored`, `mined_from_human_artifact`, or `self_distilled`. Self-distilled skills
   require more evidence to reach `approved`, following the measured gap between the two.

## Rationale

This converts "the library should be curated" from an intention into a bounded system with a
provable floor. The cap creates the competition that makes retirement meaningful; the evidence
floor prevents the premature pruning that measured *worse* than having no library; and the
contribution score measures what we actually care about — lift over solving without the skill —
rather than a raw success ratio that flatters skills applied to easy tasks.

Estimating contribution against the control arm is the piece that makes this tractable for us:
we need a `p0` baseline per task class, and the ablation arm from ADR-0003's measurement work
already produces one. The two mechanisms compose rather than competing for the same evidence.

## Consequences

- Retrieval gains an active-set filter, and the Curator gains a retirement pass; both are cheap.
- Per-skill contribution needs enough applications to estimate, so early in a library's life most
  skills sit below the evidence floor. This is the honest cold-start position: the system cannot
  retire confidently before it has evidence, and it must not pretend otherwise.
- A cap means good skills can be benched by competition, not just by poor performance. Benching
  is therefore reversible, and `active_cap_pressure` is tracked so a chronically saturated cap
  is visible rather than silently discarding value.
- Adopting the cap without the evidence floor would reproduce the harsh-retirement failure, so
  the two defaults must be changed together and are validated jointly in the eval harness.
