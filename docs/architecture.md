# Recertia Architecture

> This index replaces the former monolithic architecture document. Existing links remain valid; use the topic files below for direct references.
>
> All-in-one download (architecture + specifications + ADRs): [`architecture2.md`](architecture2.md).

- [Overview: purpose, graph rationale, planes, and memory](architecture/overview.md)
- [Task plane](architecture/task-plane.md)
- [Skill composition](architecture/skill-composition.md)
- [Library lifecycle](architecture/library-lifecycle.md)
- [Improvement plane](architecture/improvement-plane.md)
- [Operations: storage, budgets, and attempt isolation](architecture/operations.md)
- [Container sandbox: Docker/Podman setup and hardening](architecture/container-sandbox.md)
- [Single-user go-live: models, tools, jobs, retention](architecture/go-live.md)
- [OpenAI-compatible gateways (OpenRouter)](architecture/openai-compat-gateways.md)
- [Measurement integrity](architecture/measurement-integrity.md)
- [Risk and governance](architecture/risk-and-governance.md)
- [Measurement and domain scope](architecture/measurement-and-scope.md)
- [One-year technical roadmap (2026–2027)](architecture/one-year-roadmap.md)
- [Ten-year horizon: beyond prompts (exploration, ~2036)](architecture/ten-year-horizon.md)
- [Narrowing the horizon to a supportable position (prompt + analysis)](architecture/ten-year-horizon-narrowing.md)
- [Horizon objectives (worked narrowing run)](architecture/ten-year-horizon-objectives.md)
- [UX-lead review of the horizon plan](architecture/ten-year-horizon-ux-review.md)
- [Remaining work: implementation plan](architecture/remaining-work.md)
- [Incident tabletop (operator GA)](architecture/incident-tabletop.md)
- [Threat-model deltas (principal review §5, single-operator)](architecture/threat-model-deltas.md)
- [Production readiness assessment (Phase 4 gate)](architecture/production-readiness.md)
- [Product console architecture](architecture/product-console.md)
- [Goal packs (migration programs)](architecture/goal-packs.md)

Normative requirements are in the [specifications index](specifications.md).
Forward work is in the [one-year roadmap](architecture/one-year-roadmap.md) and the
[remaining-work implementation plan](architecture/remaining-work.md).
A non-normative 2036 exploration lives in the
[ten-year horizon](architecture/ten-year-horizon.md); it does not create gates.
A narrowing prompt and the resulting objectives list are
[ten-year-horizon-narrowing.md](architecture/ten-year-horizon-narrowing.md) and
[ten-year-horizon-objectives.md](architecture/ten-year-horizon-objectives.md),
fine-tuned against
[ten-year-horizon-ux-review.md](architecture/ten-year-horizon-ux-review.md).
Completed M0–M9 sequencing is archived at
[archive/2026-Q3/implementation-plan.md](archive/2026-Q3/implementation-plan.md).
The August 2026 principal review is archived at
[archive/2026-Q3/principal-review-2026-08.md](archive/2026-Q3/principal-review-2026-08.md).
