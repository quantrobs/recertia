# Architecture: OpenAI-compatible gateways (OpenRouter)

How Recertia talks to OpenRouter and similar Chat Completions gateways. Normative
contracts: [`../specifications/openai-compat-gateways.md`](../specifications/openai-compat-gateways.md).
Build order: [`../implementation-plan-openai-compat.md`](../implementation-plan-openai-compat.md).
Decision: [ADR-0013](../adr/0013-openai-compat-gateways.md). Operator recipe:
[`go-live.md`](go-live.md).

## 1. Position in the stack

```text
CLI / API / console
        │
        ▼
load_model_config()  →  provider ∈ {stub, anthropic, openai}
        │
        ▼
build_model_client()
        │
        ├─ anthropic → AnthropicModelClient (Messages API)
        └─ openai    → OpenAIModelClient (Chat Completions)
                              │
                              ├─ api.openai.com (default URL)
                              └─ OpenRouter / other gateway
                                 via RECERTIA_OPENAI_BASE_URL
                                 + optional headers / EXTRA_BODY
```

OpenRouter is **not** a third provider enum. It is an OpenAI-compatible transport
configuration. Manifest fields keep `provider: "openai"` and pin the gateway slug in
`model_id`.

## 2. Why this shape

- OpenRouter’s Chat Completions surface matches what `OpenAIModelClient` already sends
  (single-turn `model` + `messages`, Bearer auth, `usage.prompt_tokens` /
  `completion_tokens`).
- Attribution headers and routing knobs vary by gateway; env overlays avoid forking the
  client per vendor.
- Keeping one provider label simplifies verifier identity checks
  (`shares_identity_with`) and spend accounting tables.

## 3. Request path

1. Factory resolves `api_key` from `OPENAI_API_KEY` or `RECERTIA_API_KEY_ENV`.
2. Client builds `messages` from optional system + user prompt.
3. Body = `{model, messages}` ∪ `openai_compat_extra_body()` (blocked keys stripped).
4. Headers = `Authorization` + `Content-Type` ∪ `openai_compat_headers()`.
5. POST to `RECERTIA_OPENAI_BASE_URL` (must already include `/chat/completions`).
6. Text extracted from `choices[0].message.content` (string only).
7. Cost estimated via `estimate_cost_usd(provider="openai", model_id=…)`.

Implementation: `src/recertia/solver/providers.py`
(`openai_compat_headers`, `openai_compat_extra_body`, `OpenAIModelClient`).

## 4. What operators must supply

| Required | Purpose |
| --- | --- |
| `RECERTIA_MODEL_PROVIDER=openai` | Select Chat Completions client |
| `RECERTIA_MODEL_ID=<openrouter-slug>` | Exact slug (e.g. `moonshotai/kimi-k2`) |
| `OPENAI_API_KEY=sk-or-…` | OpenRouter API key as Bearer token |
| `RECERTIA_OPENAI_BASE_URL=https://openrouter.ai/api/v1/chat/completions` | Full endpoint URL |

| Recommended | Purpose |
| --- | --- |
| `RECERTIA_OPENAI_HTTP_REFERER` | App site URL for OpenRouter rankings |
| `RECERTIA_OPENAI_TITLE` | App title (`X-OpenRouter-Title` / `X-Title`) |
| `RECERTIA_OPENAI_EXTRA_BODY` | `max_tokens`, `temperature`, OpenRouter `provider` object |
| `RECERTIA_MODEL_PRICE_OPENAI_<SLUG>_IN` / `_OUT` | Honest spend for non-table models |
| Distinct `RECERTIA_VERIFIER_MODEL_ID` | Avoid solver self-judgment when possible |

## 5. Non-goals (this surface)

- Dedicated `openrouter` provider name or SDK dependency
- Token-level streaming into the Pilot UI (console SSE is run events)
- Automatic multi-provider failover / retries across gateways
- Multimodal / array `message.content` parsing
- Console secret entry for OpenRouter keys (process env / BFF only)
- Built-in price table for every OpenRouter slug

## 6. Threat and measurement notes

- Gateway keys are as privileged as OpenAI keys; treat `.env` / secret stores accordingly.
- Spend without price overrides uses default $1/$3 per MTok — **mark reports as
  approximate** until overrides are set (measurement honesty).
- Verifier sharing the same Bearer key as the solver is allowed but weaker isolation;
  prefer a distinct model id at minimum (`go-live.md` verifier split).
- Do not claim model-family assumptions (`a1`/`a2`/`a4`) supported solely because a
  gateway slug was configured (B7).
