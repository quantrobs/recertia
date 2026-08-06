# ADR-0013: OpenRouter and peers as OpenAI-compatible gateways

- **Status:** accepted
- **Date:** 2026-08-01

## Context

Operators want models hosted behind OpenRouter (and similar Chat Completions gateways)
— Kimi, Qwen, and others — without Recertia growing a dedicated client per vendor.
OpenRouter’s public API is OpenAI Chat Completions–shaped, with optional attribution
headers and gateway-specific body fields (`provider` routing, temperature, `max_tokens`).

A first-class `openrouter` provider would duplicate the OpenAI client, confuse
manifest/`provider` labels, and still need the same URL/header/body knobs.

## Decision

1. **No dedicated `openrouter` provider.** Gateways reuse
   `RECERTIA_MODEL_PROVIDER=openai` + `OpenAIModelClient`.
2. **`RECERTIA_OPENAI_BASE_URL` is the full Chat Completions URL**, not an SDK-style
   `/v1` root. Callers must set
   `https://openrouter.ai/api/v1/chat/completions` (or another gateway’s equivalent).
3. **Gateway metadata is env-driven**, not hardcoded to OpenRouter:
   - `RECERTIA_OPENAI_HTTP_REFERER` → `HTTP-Referer`
   - `RECERTIA_OPENAI_TITLE` (alias `RECERTIA_OPENROUTER_TITLE`) → `X-OpenRouter-Title` + `X-Title`
   - `RECERTIA_OPENAI_EXTRA_HEADERS` → arbitrary string headers
   - `RECERTIA_OPENAI_EXTRA_BODY` → Chat Completions fields; MUST NOT override `model` / `messages`
4. **Auth stays `OPENAI_API_KEY`** (or `RECERTIA_API_KEY_ENV`). OpenRouter keys (`sk-or-…`)
   are Bearer tokens on that same surface.
5. **Manifest / spend `provider` remains `"openai"`**; the OpenRouter slug lives in
   `model_id` (e.g. `moonshotai/kimi-k2`). Cost rates for unknown slugs use defaults or
   explicit `RECERTIA_MODEL_PRICE_*` overrides.
6. **Streaming tokens and multi-provider failover remain non-goals** of this path
   (roadmap deliberate-absence candidates). Console SSE is run-event streaming, not
   token streaming.

## Consequences

- Go-live recipe stays a small env block; Kimi/Qwen work without new packages.
- Specs: [`../specifications/openai-compat-gateways.md`](../specifications/openai-compat-gateways.md).
- Plan: [`../implementation-plan-openai-compat.md`](../archive/2026-Q3/implementation-plan-openai-compat.md).
- Architecture: [`../architecture/openai-compat-gateways.md`](../architecture/openai-compat-gateways.md).
- Operators who need accurate spend MUST set price overrides for gateway slugs.
- A future first-class `openrouter` enum would be a breaking label change and needs a
  separate ADR; this decision prefers the gateway-over-openai pattern.
