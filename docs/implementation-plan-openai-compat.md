# OpenAI-compatible gateway (OpenRouter) implementation plan

Build order for OpenRouter and peers via the OpenAI Chat Completions client. Normative
contracts: [`specifications/openai-compat-gateways.md`](specifications/openai-compat-gateways.md).
Architecture: [`architecture/openai-compat-gateways.md`](architecture/openai-compat-gateways.md).
Decision: [ADR-0013](adr/0013-openai-compat-gateways.md). Operator recipe:
[`architecture/go-live.md`](architecture/go-live.md).

**Do not estimate calendar time** — milestones are sized by dependency and what each one
unlocks.

## Guiding rules

1. **Gateway over fork.** Prefer env overlays on `OpenAIModelClient` to a new provider enum.
2. **Full URL, fail loud.** Never silently rewrite base URLs; invalid JSON env fails the call.
3. **Measurement honesty.** Unknown slugs use default rates until overrides exist — do not
   pretend vendor-exact spend.
4. **Keys stay server-side.** Browser/console never holds long-lived OpenRouter secrets.
5. **No research laundering.** Configuring Kimi/Qwen does not move `a1`/`a2`/`a4` to
   `supported` (B7).

## What is required to use OpenRouter today (OR0 — shipped)

Minimum env (calls succeed):

```bash
export RECERTIA_MODEL_PROVIDER=openai
export RECERTIA_MODEL_ID=moonshotai/kimi-k2   # exact OpenRouter slug
export OPENAI_API_KEY=sk-or-…                # OpenRouter key
export RECERTIA_OPENAI_BASE_URL=https://openrouter.ai/api/v1/chat/completions
```

Recommended:

```bash
export RECERTIA_OPENAI_HTTP_REFERER=https://github.com/your-org/your-app
export RECERTIA_OPENAI_TITLE=Recertia
export RECERTIA_OPENAI_EXTRA_BODY='{"temperature":0.2,"max_tokens":1024}'
# Honest spend (example rates — set to current OpenRouter list prices):
export RECERTIA_MODEL_PRICE_OPENAI_MOONSHOTAI_KIMI_K2_IN=…
export RECERTIA_MODEL_PRICE_OPENAI_MOONSHOTAI_KIMI_K2_OUT=…
export RECERTIA_VERIFIER_MODEL_ID=…          # distinct slug when possible
```

Qwen (and other OpenRouter models) use the same block with a different `RECERTIA_MODEL_ID`.

Landed in PR #44 + go-live docs: headers, `EXTRA_BODY` / `EXTRA_HEADERS`, unit tests
(`tests/unit/test_openai_compat_gateway.py`).

## Milestone map

```text
OR0  Call path + attribution headers + EXTRA_BODY   ✅ shipped (#44)
OR1  Operator polish: README, cost helpers, docs gate
OR2  Generation defaults + response robustness
OR3  Optional: allowlisted console model presets (no key in browser)
```

---

## OR0 — Call path (done)

**Goal:** An operator can run Recertia against OpenRouter slugs (Kimi, Qwen, …) without a
dedicated provider.

### Scope delivered

- `openai_compat_headers` / `openai_compat_extra_body` on `OpenAIModelClient`
- Full-URL `RECERTIA_OPENAI_BASE_URL`
- Go-live recipe
- Unit tests OG-1…OG-3 class coverage

### Non-goals (still true)

- Native `openrouter` provider; streaming tokens; failover; built-in Kimi/Qwen prices

---

## OR1 — Operator polish

**Goal:** Discoverability and honest spend without changing the protocol.

### Scope

- README “Models and go-live” mentions OpenRouter / openai-compat link
- Document price-env slug rules with a Kimi/Qwen example
- Optional helper: `recertia models price-env --provider openai --model-id <slug>` (or docs
  snippet only) so operators do not hand-mangle env names
- Wire architecture/spec indexes (this plan)
- Conformance: OG-5, OG-6 locked in CI if not already

### Engineering gates

- README points to go-live OpenRouter block
- Price override for a slash-containing slug demonstrably changes `estimate_cost_usd`
- Cross-ref check green

### Non-goals

- Live OpenRouter CI (requires secrets); console key UI

### Unlocks

Operators find the path without tribal knowledge; spend reports can be made accurate.

---

## OR2 — Generation defaults and response robustness

**Goal:** Fewer surprise truncations / parse failures on gateway models.

### Scope

- Documented default `max_tokens` via recommended `EXTRA_BODY` **or** a single env
  `RECERTIA_OPENAI_MAX_TOKENS` applied only when `EXTRA_BODY` omits it
- Clearer `ProviderError` when OpenRouter returns error JSON (`error.message`)
- Optional: tolerate simple list-shaped `message.content` text parts (still no vision)

### Engineering gates

- Unit tests for max-tokens default merge and error-body surfacing
- No change to Anthropic client defaults unless shared helper is intentional

### Non-goals

- Full multimodal; tool/function-calling loop via OpenRouter

### Unlocks

Fewer failed scratch turns on long Kimi/Qwen answers.

---

## OR3 — Console model presets (optional)

**Goal:** Pilot can select an allowlisted gateway slug without pasting keys.

### Scope

- Server-side allowlist of `{label, provider, model_id}` (config file or env JSON)
- Console dropdown sets run metadata that the API maps to process-configured clients
  **or** rejects unknown slugs
- Keys remain in server env / secret store only

### Engineering gates

- SPA bundle contains no secrets
- Unknown slug → 400; allowlisted slug uses same `OpenAIModelClient` path
- Works with existing console session/RBAC (C3)

### Non-goals if skipped

- Operators keep using process env + API key sidebar (acceptable for single-operator GA)

### Unlocks

Safer multi-operator demos on a shared host.

---

## Dependency graph

```text
OR0 (shipped) ──► OR1 ──► OR2
                    │
                    └────► OR3 (optional; needs console C0+)
```

OR1 may ship as docs-only. OR2 is code. OR3 depends on product console being present.

## Relationship to other plans

| Asset | Interaction |
| --- | --- |
| Go-live / operator GA | OR0 is the supported OpenRouter path |
| Console C0–C5 | Inherits process model env; OR3 adds presets |
| Roadmap failover absence | Still deliberate — not introduced here |
| Production readiness | Gateway use does not satisfy multi-tenant or assumption gates |

## Out of scope (explicit)

| Idea | Disposition |
| --- | --- |
| Anthropic Messages via OpenRouter | Separate ADR if needed; not this client |
| Embedding OpenRouter SDK | Rejected — stdlib HTTP is enough |
| Token streaming into Pilot | Deferred with console live-token non-goal |
| Marking `a1` supported after one Kimi soak | Forbidden without intervals (B7) |
