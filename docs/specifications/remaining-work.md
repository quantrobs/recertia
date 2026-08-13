# Recertia Specifications: Remaining work

Normative requirements for work that is **not yet implemented** (or is ops-gated on
shipped code). Architecture and sequencing:
[`../architecture/remaining-work.md`](../architecture/remaining-work.md). This file
does not replace shipped contracts in
[`promotion-api-and-observability.md`](promotion-api-and-observability.md),
[`evaluation-improvement-and-governance.md`](evaluation-improvement-and-governance.md),
[`product-console.md`](product-console.md), or
[`openai-compat-gateways.md`](openai-compat-gateways.md). Where those files and this
one conflict on a **shipped** behaviour, the shipped-topic file wins. Where they
conflict on a **remaining** behaviour, **this file wins** until the change lands and
those files are updated (RW-HY).

Research outcomes `a1`–`a4` MUST NOT be marked `supported` by any requirement in this
document ([`../assumptions.md`](../assumptions.md) B7).

## 1. MetricReport completeness (RW-M2 / RW-LY)

`contracts.eval.MetricReport` MUST grow the following fields (ADR-0009; regenerate
`schema/metric_report.schema.json`):

| Field | Definition | `unavailable` MUST be set when |
| --- | --- | --- |
| `library_yield` | approved skills with ≥1 later application in the window ÷ approved skills in the library snapshot | no approved skills, or application events not recorded |
| `retrieval_precision_at_3` | mean over probe items of (labelled-relevant ∩ top-3) / 3 | probe set empty or retrieve not run |
| `retrieval_decay` | Δ `retrieval_precision_at_3` per 100 skills added vs the previous stored probe snapshot | fewer than two probe snapshots, or skill-count denominator zero |

Existing fields (`causal_lift`, `curation_gap`, `practice_conversion`,
`retirement_reversal_rate`, `judge_false_pass_rate`, …) MUST keep honest
`unavailable` reasons. Adding yield/decay MUST NOT invent zeros.

`build_metric_report` MUST accept optional `approved_applied`, `approved_total`,
`precision_at_3`, `prior_precision_at_3`, `skills_added` (or equivalent observation
rows) rather than scanning the world implicitly.

`GET /v1/metrics/report` and `recertia metrics` MUST include the new fields. PC-5
(unavailable preservation) applies.

### Probe runner

1. Recertia MUST ship a command that reads `evals/probes/<task_class>.json` (schema:
   `probes[]` with `id`, `request`, optional `workdir_files`, `relevant[]` skill ids).
2. For each probe it MUST call the same `retrieve` path as a run (not a parallel
   scorer).
3. It MUST persist per-probe hits and the mean `retrieval_precision_at_3` into the
   eval store, keyed by library snapshot / `index_snapshot_id`.
4. CI MUST fail if the committed `repo-chore` probe set scores mean precision `< 0.7`
   (M1 floor, already asserted in `tests/e2e/test_m1_procedural_memory.py` — the
   runner MUST reuse that definition).
5. Unrelated / empty-relevant probes MUST still be allowed to return an empty bundle
   without failing the mean (they contribute zeros to precision, which is the point).

### Weekly cadence

When soak secrets / `RECERTIA_EVAL_DB` are present, `.github/workflows/weekly-ops.yml`
MUST:

1. Run the probe runner against the soak library.
2. Run golden `repo-chore` tasks with the policy `ablation_rate` (eval fixtures
   remain excluded from the control sample per §19).
3. Run the judge canary; attribute `judge_false_pass_rate` to
   `provider × model_version` when a real verifier is configured.
4. Upload JSON that includes `causal_lift.status` and MUST echo
   `claim=not established` when the interval includes zero.

When secrets are **absent** (default GitHub `ubuntu-latest` checkout), the workflow
MUST still emit JSON with `unavailable` reasons and MUST NOT use `|| true` to hide a
Python exception. Empty DB → successful report with holes is allowed.

## 2. Assumption status updates (RW-A)

Updating [`../assumptions.md`](../assumptions.md) is a **commit**, not a console
toggle.

| Id | MAY move to `supported` / `refuted` only if |
| --- | --- |
| `a1` | `causal_lift` Wilson interval for `repo-chore` treatment vs control excludes zero, with sample counts; or the interval is stable and includes zero (`refuted` / remains not established — authors MUST pick the status that matches the interval, not hope) |
| `a2` | certification-trial counts per active skill vs `policy.evidence_floor` are reported; majority-below-floor is a valid `refuted` |
| `a4` | live canary rates exist per verifier model version (synthetic CI alone MUST leave status `untested` or move only to `under evaluation`) |
| `a3` | Correction Miner / Curator writes over a window stayed inside T0–T2; not required for operator GA |

A milestone **Done when** MUST NOT require `a1` to be `supported`.

Negative `a1` MUST block enabling HEX/compress and Phase-3 composition-on-traffic
expansion until a written design review (ADR or remaining-work amendment).

## 3. Portfolio dual-path expiry (RW-PC)

Until `docs/architecture/portfolio-measurement.md` exists:

- `RECERTIA_PORTFOLIO_CONTROLLER` MAY select the pure vs legacy `recompute_active_set`.
- The flag MUST NOT be documented as operator configuration.
- Equivalence tests MUST remain.

After that document exists:

- Recertia MUST delete `_recompute_active_set_legacy` and the env flag.
- `recompute_active_set` MUST be the pure controller only.
- Tests MUST fail if either the flag or the legacy function reappear.

## 4. HEX and compress enablement (RW-HEX)

`ImprovementFlags.practice_hex_search` and `curator_compress` MUST default false.

A job MUST NOT run HEX search or unit-level compress unless:

1. Policy flags are true, **and**
2. The latest weekly `MetricReport` has numeric `practice_conversion`, **and**
3. `causal_lift.status` is established positive **or** an explicit ledger-noted
   recovery experiment after `a1` `refuted`, **and**
4. `JobQuota.can_admit` for `practice_hex` / `compress` succeeds at the documented
   priority (recertifier → curator retire → fail-cluster → practice band → HEX →
   compress).

Flipping `policy/default.json` alone MUST NOT bypass (2)–(4). Bypass is a T2 change
and MUST record a human actor on the ledger.

## 5. OpenAI-compatible remaining (OR1–OR3)

Extends [`openai-compat-gateways.md`](openai-compat-gateways.md).

| ID | Assertion |
| --- | --- |
| OG-7 | Docs/CI: configuring `RECERTIA_OPENAI_BASE_URL` MUST NOT be treated as evidence for `a1`. Unknown slugs MUST cost via defaults/overrides without claiming vendor-exact spend |
| OG-8 | When `RECERTIA_OPENAI_MAX_TOKENS` is set and EXTRA_BODY does not include `max_tokens`, the client MUST send that integer |
| OG-9 | OpenRouter-style `{error: {message, code}}` bodies MUST raise `ProviderError` whose message includes the gateway `code` when present |
| OG-10 | If `choices[0].message.content` is a list of `{type: text, text}` parts, the client MUST concatenate `text` fields; other part types MAY be ignored |
| OG-11 (OR3, optional) | `POST /v1/runs` with a console-selected model slug not on the server allowlist MUST return 400; the allowlist MUST NOT be shipped in `console/static/` |

OR0 tests OG-1…OG-6 remain required.

## 6. HTTP/CLI remainder (RW-SUR)

### 6.1 Error envelope

JSON error responses under `/v1/*` SHOULD use:

```json
{ "error": { "code": "budget_exhausted", "message": "...", "run_id": "01J…", "retryable": false } }
```

`code` MUST be a stable snake_case token. `retryable` MUST be true only for
rate-limit / lock-timeout / worker-busy. FastAPI `{detail: ...}` MAY remain on
`/health` and on 422 validation until this milestone; new routes MUST use the
envelope.

### 6.2 Remaining routes

| Method | Path | MUST |
| --- | --- | --- |
| `POST` | `/v1/evals/runs` | Scope `metrics` or `admin`. Body: `task_class`, optional `snapshot` / `golden_dir`. Runs golden fixtures; writes `EvalObservation`; MUST NOT distill (eval firewall). |
| `GET` | `/v1/reviews` | List pending distill-review decisions; tenant-scoped. Until volume exists, MAY be an alias of pending skill candidates. |
| `POST` | `/v1/reviews/{decision_id}` | `approve` / `reject` / `request_changes`; ledger actor required. MUST NOT write `lifecycle=approved` (golden gate still required). |
| `GET` | `/v1/facts` · `/v1/cases` · `/v1/affordances` | Tenant-scoped reads; no cross-tenant ids (PC-1). |
| `POST` | `/v1/memory/query` | Federated retrieve debug: scores + drop reasons across planes; MUST NOT start a run. |
| `GET` | `/v1/policy` | Return loaded `Policy` (no secrets). |
| `POST` | `/v1/policy/proposals` | T2 proposal only; MUST NOT apply without human approval + eval-compare. |

CLI twins SHOULD exist for eval-run, policy show, and memory query. Other CLI twins
are SHOULD, not a gate.

### 6.3 Promotion-api drift (RW-HY)

[`promotion-api-and-observability.md`](promotion-api-and-observability.md) §9 MUST
list as implemented every route that `src/recertia/api/` currently serves, including
console C0–C4. The aspirational table MUST contain only §6.2 plus C5.

README license text MUST match `LICENSE` (PolyForm Noncommercial).

## 7. Operator-GA ops artifacts (RW-GA)

Engineering MUST keep:

- `docker-compose.soak.yml` + `scripts/soak_postgres.py`
- `.github/workflows/weekly-ops.yml` (metrics JSON + canary + postgres migrations)
- [incident-tabletop.md](../architecture/incident-tabletop.md)

Ops (not CI) MUST produce:

1. A soak log with four consecutive weeks, each pointing at a metrics artifact whose
   eval DB was not empty **or** an explicit `unavailable` reason that is not "fresh
   checkout".
2. A tabletop log: date, run id, restore source, time-to-recover, follow-up.
3. Baseline `MetricReport` from real (non-fixture) `repo-chore` runs.

GA MUST NOT be declared in README Status while (1)–(3) are missing.

## 8. Phase-4 / C5 (RW-C5, RW-TM)

Until [production-readiness.md](../architecture/production-readiness.md) go/defer
passes:

- Console MUST NOT present a tenant switcher that implies isolation it does not have.
- APIs MUST still isolate by `tenant_id` (already required).
- C5 UI MUST NOT ship.

If the gate passes, [`product-console.md`](product-console.md) §7 applies in full.
Threat-model deltas from the principal review MUST be closed or accepted-with-owner
in production-readiness.md before C5.

`research-synthesis` real traffic MUST use the existing graph and contracts. Any
structural change required is a defect in the shared layer, not a domain fork.

## 9. Explicit non-requirements

- Auto-advance / DAG / `copy_forward` for goal packs
- UNC registered-workspace roots
- Provider token streaming in the console
- Enabling HEX/compress to "get data for a1"
- A third task class
- Replacing the in-house eval harness
- Calendar estimates as done-when

## 10. Conformance tests (CI)

| ID | Assertion |
| --- | --- |
| RW-1 | `MetricReport` schema includes `library_yield`, `retrieval_precision_at_3`, `retrieval_decay`; extra=forbid |
| RW-2 | Synthetic window with no applications sets `unavailable["library_yield"]` and leaves the field `null` |
| RW-3 | Two probe snapshots with known precision 1.0 then 0.7 and +100 skills → `retrieval_decay` = −0.3 |
| RW-4 | Probe runner on committed `evals/probes/repo-chore.json` mean ≥ 0.7 |
| RW-5 | Weekly report JSON includes `causal_lift.status` or `unavailable["causal_lift"]`; never a bare float that spans a zero interval labelled as improvement |
| RW-6 | HEX job with flags true but `practice_conversion` unavailable does not emit HEX proposals |
| RW-7 | `POST /v1/evals/runs` on a fixture task does not write a candidate skill |
| RW-8 | Budget-exhausted `POST /v1/runs` body matches the error envelope (`error.code`) |
| RW-9 | OG-7…OG-10 (when OR2 lands); OG-11 when OR3 lands |
| RW-10 | After portfolio expiry, `RECERTIA_PORTFOLIO_CONTROLLER` is not read |

Tests RW-1…RW-4 are the first merge slice of RW-M2. RW-6–RW-10 land with their
milestones. Until a test exists, the ID is a specification, not a green check.
