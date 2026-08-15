"""Unit tests for StubModelClient basics."""

from __future__ import annotations

import pytest

from recertia.solver.model import ModelSpend, StubModelClient


def test_stub_queue_and_spend_accounting() -> None:
    client = StubModelClient(responses=["first", "second"], max_retries=0)
    r1 = client.complete("prompt one")
    r2 = client.complete("prompt two")
    assert r1.text == "first"
    assert r2.text == "second"
    assert client.spend.calls == 2
    assert client.spend.tokens > 0
    assert isinstance(client.spend, ModelSpend)


def test_stub_mapper_and_default_noop() -> None:
    mapped = StubModelClient(mapper=lambda prompt: f"echo {prompt}")
    assert mapped.complete("hi").text == "echo hi"

    empty = StubModelClient()
    assert "stub model" in empty.complete("anything").text


def test_stub_retries_then_raises() -> None:
    class Flaky(StubModelClient):
        def _complete_once(self, prompt: str, *, system: str | None):
            raise RuntimeError("provider down")

    client = Flaky(max_retries=1, retry_backoff_s=0.0)
    with pytest.raises(RuntimeError, match="provider down"):
        client.complete("x")
    assert client.spend.calls == 0
