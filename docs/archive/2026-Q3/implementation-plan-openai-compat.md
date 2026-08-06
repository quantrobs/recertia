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
export RECERTIA_VERIFIER_MODEL_ID=…          # distinct slug when possible
```

Landed in PR #44 + go-live docs: headers, `EXTRA_BODY` / `EXTRA_HEADERS`, unit tests.

## Milestone map

```text
OR0  Call path + attribution headers + EXTRA_BODY   ✅ shipped (#44)
OR1  Operator polish: README, cost helpers, docs gate
OR2  Generation defaults + response robustness
OR3  Optional: allowlisted console model presets (no key in browser)
```

## OR0 — Call path (done)

**Goal:** An operator can run Recertia against OpenRouter without code changes.

Shipped: env overlays, attribution headers, EXTRA_BODY, unit tests.

## OR1 — Operator polish

**Goal:** Docs and cost helpers so spend is not silent zeros.

- README / go-live recipe for OpenRouter
- Price override env vars documented
- Docs gate that gateway use does not claim `a1` supported

## OR2 — Generation defaults and response robustness

**Goal:** Fewer surprise truncations / parse failures on gateway models.

- Default max_tokens via EXTRA_BODY or RECERTIA_OPENAI_MAX_TOKENS
- Clearer ProviderError on OpenRouter error JSON
- Optional simple list-shaped message.content tolerance

## OR3 — Console model presets (optional)

**Goal:** Pilot can select an allowlisted gateway slug without pasting keys.

- Server-side allowlist; SPA has no secrets; unknown slug → 400

## Out of scope

Anthropic Messages via OpenRouter; embedding OpenRouter SDK; token streaming into Pilot;
marking research assumptions supported after one soak.
