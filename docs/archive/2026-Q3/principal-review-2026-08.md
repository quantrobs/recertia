# Principal architecture review — August 2026

External review of the Recertia system at commit `5ed5e3b` (post-#40 go-live wiring).

## Verdict

The architecture is sound, unusually measurement-honest, and structurally complete through
M0–M9. Remaining risks are operational and evidential, not design. Next twelve months:
~70% measurement and operations, ~30% new capability. Multi-tenant is a Phase-4 gate decision.

**Update:** Phase-1 P0 engineering gates P0-1…P0-5 are implemented on `main` (cost accounting,
command policy + untrusted delimiters, observe–act scratch loop, run-manifest pinning,
soak/backup guidance in go-live.md). Remaining Phase-1 work is weekly soak ops cadence.

## Settled decisions (do not re-litigate)

1. Contracts as structural source of truth (ADR-0009)
2. Engineering-gate / research-outcome split (assumptions.md hygiene CI)
3. T0–T3 self-modification boundary (ADR-0005)
4. Criteria integrity: pre-registration, hash-bound sensitivity, advisory downgrade, fresh-context judges
5. Library lifecycle: version/status/stats split, bounded active set, evidence floor
6. Attempt isolation and fan-out integrity
7. Security remediation (#39) and go-live wiring (#40)

## Production gaps (summary)

**P0 (operator GA):** cost accounting on real providers; prompt-injection path via fetch;
observe–act scratch loop; run manifest pinning; live soak/durability.

**P1 (measurement under traffic):** eval cadence; judge false-pass canary; trajectory replay as
Curator evidence; curation_gap reporting; practice loop cadence.

**P2 (scale / tenant):** Postgres soak; cross-scope promotion; tenant quotas; deployment topology;
model-provider failover policy.

## Non-goals (next twelve months)

No weight training or online RL; no multi-tenant GA before Phase-4 gate; no third task class
before Phase 4; no engine rewrite; no auto-promotion past golden gate; no vendor eval platform
replacing the in-house harness.

Full original review text with tables and threat-model deltas is recoverable from git history
(commit prior to archive). Forward plan: [`architecture/one-year-roadmap.md`](../../architecture/one-year-roadmap.md).
