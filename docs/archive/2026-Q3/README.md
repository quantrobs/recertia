# Archived docs — 2026 Q3

Completed build and review narratives removed from the active `docs/` tree to reduce clutter.
Thin stubs at the original paths keep relative links stable.

| File | Original role |
| --- | --- |
| `implementation-plan.md` | M0–M9 build order (CI still parses this copy) |
| `implementation-plan-*.md` | Feature-specific build plans |
| `refactor-plan.md` | Pre-M0 design blockers B1–B7 / R0–R5 |
| `principal-review-2026-08.md` | External architecture review snapshot |

Active documentation: ADRs, specifications, architecture topics, `assumptions.md`,
`references.md`, and `architecture/one-year-roadmap.md`.

Score-10 research extracts live under [`../../research/score10-references/`](../../research/score10-references/).

## History recovery

Some archive bodies here are condensed CI/navigation copies. The full pre-archive text of long plans
and the principal review is recoverable from git history (commits before `f6e2afb` and related
archive commits on `main`). Prefer `git show <pre-archive-sha>:docs/implementation-plan.md` (etc.)
when you need the original long form.
