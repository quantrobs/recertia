"""HTTP model providers (Anthropic Messages + OpenAI Chat Completions).

Uses the standard library only so the core package stays dependency-light. Optional
extras may wrap richer SDKs later; these clients are enough for single-user go-live.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from recertia.solver.model import ModelClient, ModelResponse


class ProviderError(RuntimeError):
    """Provider rejected the request or returned an unusable payload."""


def _http_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ProviderError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"network error calling {url}: {exc}") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"non-JSON response from {url}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError(f"unexpected JSON payload from {url}")
    return parsed


class AnthropicModelClient(ModelClient):
    """Anthropic Messages API client."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        max_retries: int = 2,
        timeout_s: float = 60.0,
        role: str = "solver",
        credential_id: str | None = None,
        base_url: str = "https://api.anthropic.com/v1/messages",
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(
            max_retries=max_retries,
            timeout_s=timeout_s,
            provider="anthropic",
            model_id=model_id,
            role=role,
            credential_id=credential_id or "ANTHROPIC_API_KEY",
        )
        self._api_key = api_key
        self._base_url = base_url
        self._max_tokens = max_tokens

    def _complete_once(self, prompt: str, *, system: str | None) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        payload = _http_json(
            self._base_url,
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            body=body,
            timeout_s=self.timeout_s,
        )
        text = _anthropic_text(payload)
        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens") or max(1, len(prompt) // 4))
        completion_tokens = int(usage.get("output_tokens") or max(1, len(text) // 4))
        from recertia.solver.pricing import estimate_cost_usd

        return ModelResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost_usd(
                provider="anthropic",
                model_id=str(self.model_id or "anthropic"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
            model=str(self.model_id or "anthropic"),
        )


class OpenAIModelClient(ModelClient):
    """OpenAI-compatible Chat Completions client."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        max_retries: int = 2,
        timeout_s: float = 60.0,
        role: str = "solver",
        credential_id: str | None = None,
        base_url: str = "https://api.openai.com/v1/chat/completions",
    ) -> None:
        super().__init__(
            max_retries=max_retries,
            timeout_s=timeout_s,
            provider="openai",
            model_id=model_id,
            role=role,
            credential_id=credential_id or "OPENAI_API_KEY",
        )
        self._api_key = api_key
        self._base_url = base_url

    def _complete_once(self, prompt: str, *, system: str | None) -> ModelResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = _http_json(
            self._base_url,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self._api_key}",
            },
            body={"model": self.model_id, "messages": messages},
            timeout_s=self.timeout_s,
        )
        text = _openai_text(payload)
        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or max(1, len(prompt) // 4))
        completion_tokens = int(usage.get("completion_tokens") or max(1, len(text) // 4))
        from recertia.solver.pricing import estimate_cost_usd

        return ModelResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost_usd(
                provider="openai",
                model_id=str(self.model_id or "openai"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
            model=str(self.model_id or "openai"),
        )


def _anthropic_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        raise ProviderError("anthropic response missing content blocks")
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    text = "".join(parts).strip()
    if not text:
        raise ProviderError("anthropic response contained no text")
    return text


def _openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("openai response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ProviderError("openai response missing message")
    text = str(message.get("content") or "").strip()
    if not text:
        raise ProviderError("openai response contained no text")
    return text
