# ADR-0005: Tiered self-modification boundary

- **Status:** accepted

## Context

Once the system improves its own machinery — distiller guidance, retrieval thresholds, routing
and budget policy — the question "what may it change about itself?" needs an answer in the
architecture rather than in reviewer instinct.

The failure here is not malice, it is honest optimisation. A system rewarded for
`first_attempt_success` and cost can improve both by lowering the promotion bar, weakening
criteria, shrinking the ablation control arm, or granting itself broader tool permissions.
Each of those is a locally rational change that destroys the evidence base the whole design
rests on. The first draft had no statement of which knobs were in scope, so by default
everything the code could reach was.

## Decision

Classify every mutable surface into four tiers, and enforce the classification in code:

| Tier | Scope | Mechanism |
| --- | --- | --- |
| **T0 — autonomous** | Trust scores, affordance aggregates, episodic cases, retrieval caches | Written by runs; derived and revertible |
| **T1 — policy-gated** | Skill and fact versions, curator proposals, shadow promotions | Auto-promote only with eval evidence and zero regressions |
| **T2 — human-gated** | Distiller guidance, criteria templates, retrieval thresholds, routing and escalation ladder, budget defaults | Versioned config, human approval plus eval comparison |
| **T3 — never autonomous** | Tool registry and side-effect classes, sandbox policy, promotion thresholds, ablation rate, graph topology, this boundary | Human-authored code or config review only |

The governing rule: **the system may not modify the mechanisms that measure or constrain it.**

## Rationale

Tiering by *what a change can compromise* rather than by risk intuition gives a test that
survives new features: if a surface can affect measurement integrity, containment, or the
promotion bar, it is T3; if it changes behaviour but is measurable by an untouched harness, it
is T2 or T1; if it is derived data, it is T0.

This also lets autonomy expand safely. Shadow promotion (T1) can retire human approval for
skills precisely because the thresholds governing it are T3 and cannot move underneath it.

## Consequences

- Policy is a versioned artifact with an approval path, not runtime state.
- The eval harness, ablation sampler, promotion thresholds, and sandbox policy must be
  unreachable from any code path a run or job can invoke — enforced by module boundaries and
  asserted in CI, not by convention.
- T2 changes are still improvements and must be evidenced: propose, run golden sets against both
  configs, show lift, then a human approves.
- Self-authored tools are out of scope by construction, since a system that writes its own tools
  writes its own permissions.
- New surfaces must be tiered when introduced; an untiered mutable surface is a review blocker.
