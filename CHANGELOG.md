# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Notes

Research outcomes `a1`–`a4` stay in [`docs/assumptions.md`](docs/assumptions.md)
until real traffic produces intervals. Remaining ops gates:
[`docs/architecture/remaining-work.md`](docs/architecture/remaining-work.md).
