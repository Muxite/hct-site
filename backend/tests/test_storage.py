"""Unit tests for storage.py's Supabase Storage download (mocked httpx, no
live network calls)."""

from __future__ import annotations

import httpx
import pytest

from src import storage


def test_download_object_writes_bytes_to_dest(tmp_path):
    seen = {}

    def routes(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers.get("apikey")
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"docx-bytes")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    dest = tmp_path / "inbox" / "fels-cv.docx"
    out = storage.download_object(
        "https://proj.supabase.co", "sekret", "cv-uploads", "cv/current.docx", dest,
        client=client,
    )

    assert out == dest
    assert dest.read_bytes() == b"docx-bytes"
    assert seen["url"] == "https://proj.supabase.co/storage/v1/object/cv-uploads/cv/current.docx"
    assert seen["apikey"] == "sekret"
    assert seen["authorization"] == "Bearer sekret"


def test_download_object_creates_missing_parent_dirs(tmp_path):
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    dest = tmp_path / "a" / "b" / "c.docx"
    assert not dest.parent.exists()
    storage.download_object(
        "https://x.supabase.co", "k", "bucket", "obj.docx", dest, client=client,
    )
    assert dest.exists()


def test_download_object_strips_trailing_slash_from_sb_url(tmp_path):
    seen = {}

    def routes(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"x")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    storage.download_object(
        "https://x.supabase.co/", "k", "cv-uploads", "cv/current.docx",
        tmp_path / "out.docx", client=client,
    )
    assert seen["url"] == "https://x.supabase.co/storage/v1/object/cv-uploads/cv/current.docx"


def test_download_object_raises_storage_error_on_http_error(tmp_path):
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    dest = tmp_path / "out.docx"
    with pytest.raises(storage.StorageError):
        storage.download_object(
            "https://x.supabase.co", "k", "cv-uploads", "cv/current.docx", dest,
            client=client,
        )
    assert not dest.exists()  # failure before any bytes are written


def test_download_object_requires_url_and_key(tmp_path):
    with pytest.raises(storage.StorageError):
        storage.download_object("", "k", "bucket", "obj", tmp_path / "out")
    with pytest.raises(storage.StorageError):
        storage.download_object("https://x.supabase.co", "", "bucket", "obj", tmp_path / "out")
