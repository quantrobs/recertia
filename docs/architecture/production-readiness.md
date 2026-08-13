# Production readiness assessment (Phase 4 gate)

Companion to [`one-year-roadmap.md`](one-year-roadmap.md) §5 and
[`archive/2026-Q3/principal-review-2026-08.md`](../archive/2026-Q3/principal-review-2026-08.md) §5. Every row must be
**closed** or **accepted-with-owner** before multi-tenant GA is considered.

| Item | Status | Owner / notes |
| --- | --- | --- |
| Threat-model deltas from principal review §5 | accepted-with-owner (single-operator) | See [`threat-model-deltas.md`](threat-model-deltas.md). Re-review + second-party signature before tenant GA. C5 UI still must not ship. |
| Break-glass procedure | accepted-with-owner | Operator retains host access to `.recertia/` and `DATABASE_URL`; document in runbook |
| Key rotation | closed (scaffold) | `recertia keys revoke` + re-issue; rotate provider keys out-of-band |
| Deployment topology | accepted-with-owner | Single-operator: CLI + optional API on loopback; container backend preferred |
| SLOs (run p95, eval cadence, canary miss) | closed (scaffold) | Tracked via `recertia metrics` + weekly-ops workflow; alert thresholds operator-owned |
| Tenant quota accounting | closed (scaffold) | `QuotaStore` on `POST /v1/runs`; env `RECERTIA_TENANT_MAX_*` |
| Scope / planted-secret isolation | closed (CI) | `tests/e2e/test_planted_secret_scope.py` |
| Second domain unchanged runtime | closed (fixture + CI) | `evals/golden/research-synthesis/` + `second_domain_fixture_ready` |
| NIST AI RMF Govern/Map (tenant surface) | open | Required only if multi-tenant GA proceeds |
| Assumption `a1` / `a2` resolved on real traffic | research | Must not be marked `supported` without intervals (B7) |
| Multi-tenant GA gate | deferred until criteria met | Operator GA + `a1` supported in ≥1 domain + P2 closed + signed threat model |
| Product console C5 (tenant switcher) | deferred until criteria met | See [`product-console.md`](product-console.md); C0–C4 single-operator console may proceed earlier |

## Multi-tenant go / defer

Proceed only if all of the following hold:

1. Operator mode has been GA for a full phase (four consecutive soak weeks).
2. `a1` is `supported` in at least one domain with a stated interval.
3. All P2 rows from the principal review are closed or accepted-with-owner.
4. A written threat model is signed by someone other than its author.

Otherwise the year ends with a two-domain single-operator product — an acceptable outcome.
