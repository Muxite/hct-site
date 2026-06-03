"""Unit tests for the OpenRouter client (httpx MockTransport, no live calls)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.llm import LLMError, OpenRouterClient
from src.metrics import UsageTracker


def _make(handler, *, tracker: UsageTracker | None = None) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://openrouter.ai/api/v1")
    return OpenRouterClient(
        "test-key", model="google/gemini-3-flash-preview", client=http, tracker=tracker
    )


def test_complete_sends_expected_payload_and_returns_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    with _make(handler) as c:
        out = c.complete(system="sys", user="usr")
    assert out == "hello"
    assert seen["model"] == "google/gemini-3-flash-preview"
    assert seen["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["messages"][1] == {"role": "user", "content": "usr"}
    assert seen["response_format"] == {"type": "json_object"}


def test_json_mode_can_be_disabled():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    with _make(handler) as c:
        c.complete(system="s", user="u", json_mode=False)
    assert "response_format" not in seen


def test_usage_is_recorded_on_tracker():
    tracker = UsageTracker(label="extract")

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        })

    with _make(handler, tracker=tracker) as c:
        c.complete(system="s", user="u", label="extract")
    assert tracker.totals["calls"] == 1
    assert tracker.totals["prompt_tokens"] == 120
    assert tracker.totals["total_tokens"] == 150
    assert tracker.records[0].label == "extract"
    assert tracker.totals["cost_usd"] > 0


def test_failed_call_records_not_ok():
    tracker = UsageTracker()

    def handler(request):
        return httpx.Response(500, text="boom")

    with _make(handler, tracker=tracker) as c:
        with pytest.raises(LLMError):
            c.complete(system="s", user="u")
    assert tracker.records and tracker.records[0].ok is False


def test_http_error_becomes_llmerror():
    def handler(request):
        return httpx.Response(429, text="rate limited")

    with _make(handler) as c:
        with pytest.raises(LLMError):
            c.complete(system="s", user="u")


def test_missing_content_becomes_llmerror():
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    with _make(handler) as c:
        with pytest.raises(LLMError):
            c.complete(system="s", user="u")


def test_empty_content_becomes_llmerror():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with _make(handler) as c:
        with pytest.raises(LLMError):
            c.complete(system="s", user="u")
