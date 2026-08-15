# Threat-model deltas (principal review §5) — single-operator closeout

Companion to [`remaining-work.md`](remaining-work.md). Rows below are
**closed** or **accepted-with-owner** for **single-operator** mode. They are **not** a
signed multi-tenant threat model and do **not** authorize console C5.

NIST AI RMF Govern/Map remains open and tenant-only. Assumption `a4` stays `untested`
until live canary rates exist (B7: this document MUST NOT mark research assumptions
`supported`).

| Threat | Path | Control today | Single-operator status |
| --- | --- | --- | --- |
| Indirect prompt injection via fetched content | `fetch` → prompt → `agent_subtask` | Untrusted delimiters + command policy (P0-2); container backend is the production default; `--local-exec` is break-glass | **accepted-with-owner**: residual is high only under `--local-exec`; operator owns that choice |
| Solver/verifier credential sharing | Same provider account for both models | `shares_identity_with` blocks identical (provider, model, credential) triples; `recertia canary` warns when `RECERTIA_MODEL_ID` equals `RECERTIA_VERIFIER_MODEL_ID` | **accepted-with-owner**: prefer a distinct verifier slug and credential on the soak host |
| Memory poisoning via distilled content | Model-authored skills/facts re-enter context | Hygiene scan, provenance-weighted trust, review gate, golden gate before `lifecycle=approved` | **accepted-with-owner**: scan is signature-based; distiller output stays data |
| Cost blowup through solver loop and fan-out | Loops × branches × retries | Token/cost on `ModelResponse`; `Budget.max_cost_usd`; tenant quotas | **closed (scaffold)**: P0-1 landed; operator still sets quotas |
| Judge/model compromise | Drifting judge inflates pass rates | Judge isolation; planted-failure canary (`recertia canary`); optional `--live` path attributes `provider × model_version` | **accepted-with-owner**: synthetic canary is in CI; live rates are ops (`a4` untested) |
| Transcript secret capture | Prompts/excerpts persisted in transcripts | Transcripts are operator-local under `.recertia/` | **accepted-with-owner** for single-user; **reopen at the tenant gate** |

## Explicit non-claims

- This file is not a signature by a second party. Multi-tenant GA still requires a threat
  model signed by someone other than its author.
- Console C5 (tenant switcher) MUST NOT ship on the strength of this closeout.
- Model-provider failover (P2-5) remains a deliberate-absence candidate.
