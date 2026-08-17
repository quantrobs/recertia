# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Extract Method on the walk: `solve` is a strategy switch into sibling modules,
  `distill` is named honesty gates, `Retriever.search` is stage calls, `_execute`
  is hop / route / snapshot / checkpoint.
- Split `SearchCapability` from `IndexMaintenance`. The retrieve node cannot
  rebuild or upsert. Debug `federated_query` refuses a stale index instead of
  rebuilding it.
- One `retirement_decision` predicate. `propose_retirements` and
  `maybe_bench_on_contribution` are adapters. The Curator job now applies
  proposals; `recompute_active_set` still does not bench.
- `estimate_contribution(..., has_required_non_judge)` is required. Judge-only
  samples produce `estimate is None`.

### Added

- `assemble_bundle` shared by retrieve and the debug query. Affordance flake
  thresholds live on `RetrievalConfig`.
- `GraphOrchestrator(on_finalize=...)` callback. Eval recording moved to the
  composition root so `recertia.graph` no longer imports `EvalStore`.

## [0.1.0] - 2026-08-15

First public preview. Engineering through M0–M9 is on `main`. Operator-mode GA
(soak weeks, tabletop log, live `repo-chore` metrics) is still open; do not read
this version as production-ready.

### Added

- Contracts-as-code (`contracts/`) with generated JSON Schema (`schema/`)
- Graph runtime, plural memory planes, golden-gated promotion, control-arm lift
- CLI (`recertia`) and optional FastAPI console (Pilot / Tower / Ops)
- Container execution backend (Docker/Podman); `--local-exec` for development
- Seed skills and golden evals under `skills/` and `evals/`
- PolyForm Noncommercial license (`LICENSE`, `NOTICE`), `SECURITY.md`, and `CONTRIBUTING.md`
- Canonical GitHub identity locked to `github.com/recertia/recertia` (clone URL, package
  metadata, and contributor guide). `pyproject.toml` is parsed in CI so a duplicate
  `license` key cannot break install again.

### Notes

Research outcomes `a1`–`a4` stay in [`docs/assumptions.md`](docs/assumptions.md)
until real traffic produces intervals. Remaining ops gates:
[`docs/architecture/remaining-work.md`](docs/architecture/remaining-work.md).
