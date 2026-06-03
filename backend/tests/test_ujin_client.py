"""Unit tests for the ujin scrape client (against an httpx MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.ujin_client import ScrapeResult, UjinClient, _extract_text


def _client(handler) -> UjinClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://ujin:8901")
    return UjinClient(client=http)


def test_scrape_article_mode_extracts_text_and_fingerprint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/scrape"
        body = json.loads(request.content)
        assert body == {
            "url": "https://scholar.example/x",
            "mode": "article",
            "force_refresh": False,
        }
        return httpx.Response(
            200,
            json={
                "url": "https://scholar.example/x",
                "kind": "article",
                "fingerprint": "abc123",
                "used_renderer": True,
                "strategy_used": "obscura",
                "article": {"url": "...", "title": "Pubs", "text": "Paper one\nPaper two"},
            },
        )

    with _client(handler) as c:
        res = c.scrape("https://scholar.example/x")
    assert isinstance(res, ScrapeResult)
    assert res.fingerprint == "abc123"
    assert res.used_renderer is True
    assert res.strategy_used == "obscura"
    assert res.text == "Pubs\n\nPaper one\nPaper two"
    assert res.ok is True


def test_scrape_passes_mode_and_force_refresh():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"url": "u", "kind": "links", "fingerprint": "f", "links": []})

    with _client(handler) as c:
        c.scrape("u", mode="links", force_refresh=True)
    assert captured["mode"] == "links"
    assert captured["force_refresh"] is True


def test_extract_text_from_links():
    data = {
        "links": [
            {"text": "Paper A", "url": "https://a"},
            {"text": "Paper B", "url": "https://b"},
        ]
    }
    assert _extract_text(data) == "- Paper A (https://a)\n- Paper B (https://b)"


def test_extract_text_from_structured():
    data = {"structured": {"jsonld": {"name": "x"}}}
    out = _extract_text(data)
    assert "jsonld" in out and "name" in out


def test_empty_response_is_not_ok():
    res = ScrapeResult(url="u", kind="empty", fingerprint="", text="", used_renderer=False, strategy_used="http")
    assert res.ok is False


def test_http_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _client(handler) as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.scrape("https://x")


def test_health_true_on_200_false_on_error():
    def ok(request):
        return httpx.Response(200, json={"status": "ok"})

    def bad(request):
        return httpx.Response(503)

    with _client(ok) as c:
        assert c.health() is True
    with _client(bad) as c:
        assert c.health() is False
