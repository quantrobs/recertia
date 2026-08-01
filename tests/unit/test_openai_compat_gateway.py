"""OpenAI-compatible gateway extras (OpenRouter headers / body)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from recertia.solver.providers import (
    OpenAIModelClient,
    ProviderError,
    openai_compat_extra_body,
    openai_compat_headers,
)


def test_openai_compat_headers_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECERTIA_OPENAI_HTTP_REFERER", "https://example.com/app")
    monkeypatch.setenv("RECERTIA_OPENAI_TITLE", "Recertia")
    monkeypatch.setenv(
        "RECERTIA_OPENAI_EXTRA_HEADERS",
        '{"X-Custom":"abc"}',
    )
    headers = openai_compat_headers()
    assert headers["HTTP-Referer"] == "https://example.com/app"
    assert headers["X-OpenRouter-Title"] == "Recertia"
    assert headers["X-Title"] == "Recertia"
    assert headers["X-Custom"] == "abc"


def test_openai_compat_extra_body_blocks_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RECERTIA_OPENAI_EXTRA_BODY",
        '{"temperature":0.1,"model":"evil","messages":[]}',
    )
    extra = openai_compat_extra_body()
    assert extra == {"temperature": 0.1}


def test_openai_client_sends_gateway_headers_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECERTIA_OPENAI_HTTP_REFERER", "https://example.com")
    monkeypatch.setenv("RECERTIA_OPENROUTER_TITLE", "demo")
    monkeypatch.setenv("RECERTIA_OPENAI_EXTRA_BODY", '{"temperature":0.3}')
    captured: dict = {}

    def _fake_http(url: str, *, headers: dict, body: dict, timeout_s: float) -> dict:
        captured["headers"] = headers
        captured["body"] = body
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    with patch("recertia.solver.providers._http_json", side_effect=_fake_http):
        client = OpenAIModelClient(
            api_key="sk-or-test",
            model_id="moonshotai/kimi-k2",
            base_url="https://openrouter.ai/api/v1/chat/completions",
        )
        client.complete("hi")

    assert captured["headers"]["authorization"] == "Bearer sk-or-test"
    assert captured["headers"]["HTTP-Referer"] == "https://example.com"
    assert captured["headers"]["X-OpenRouter-Title"] == "demo"
    assert captured["body"]["model"] == "moonshotai/kimi-k2"
    assert captured["body"]["temperature"] == 0.3
    assert captured["body"]["messages"][-1]["content"] == "hi"


def test_openai_extra_headers_must_be_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECERTIA_OPENAI_EXTRA_HEADERS", "[1,2]")
    with pytest.raises(ProviderError, match="JSON object"):
        openai_compat_headers()
