"""Unit tests for the thin Supabase PostgREST client (httpx MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from src.supabase_client import SupabaseClient, SupabaseError


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return SupabaseClient("https://proj.supabase.co", "secret-key", client=http)


def test_requires_url_and_key():
    with pytest.raises(SupabaseError):
        SupabaseClient("", "key")
    with pytest.raises(SupabaseError):
        SupabaseClient("https://x", "")


def test_upsert_sends_auth_and_merge_prefer():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["apikey"] = req.headers.get("apikey")
        seen["prefer"] = req.headers.get("prefer")
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={})

    sb = _client(handler)
    n = sb.upsert("publications", [{"slug": "a", "title": "A"}], on_conflict="slug")
    assert n == 1
    assert seen["url"].endswith("/rest/v1/publications?on_conflict=slug")
    assert seen["auth"] == "Bearer secret-key"
    assert seen["apikey"] == "secret-key"
    assert "merge-duplicates" in seen["prefer"]
    assert seen["body"] == [{"slug": "a", "title": "A"}]


def test_upsert_empty_is_noop():
    def handler(req):  # pragma: no cover - should not be called
        raise AssertionError("no request expected for empty rows")

    assert _client(handler).upsert("publications", []) == 0


def test_upsert_raises_on_http_error():
    sb = _client(lambda req: httpx.Response(400, json={"message": "bad"}))
    with pytest.raises(SupabaseError):
        sb.upsert("publications", [{"slug": "a"}])


def test_replace_deletes_then_inserts():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url)))
        return httpx.Response(200, json={})

    sb = _client(handler)
    n = sb.replace("timeline", [{"position": 0}, {"position": 1}], key="position")
    assert n == 2
    assert calls[0][0] == "DELETE"
    assert "position=not.is.null" in calls[0][1]
    assert calls[1][0] == "POST"


def test_select_returns_rows():
    rows = [{"slug": "a", "title": "A"}]
    sb = _client(lambda req: httpx.Response(200, json=rows))
    assert sb.select("publications") == rows


def test_update_patches_matching_rows():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["url"] = str(req.url)
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={})

    sb = _client(handler)
    sb.update("publications", {"project_slug": "b2s"}, params={"slug": "in.(a,b)"})
    assert seen["method"] == "PATCH"
    assert "slug=in.%28a%2Cb%29" in seen["url"] or "slug=in.(a,b)" in seen["url"]
    assert '"project_slug"' in seen["body"]


def test_update_requires_filter():
    with pytest.raises(SupabaseError, match="non-empty filter"):
        _client(lambda req: httpx.Response(200)).update("publications", {"x": 1}, params={})
