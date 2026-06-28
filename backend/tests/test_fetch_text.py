"""Unit tests for article fetching (PDF vs HTML routing, MockTransport)."""

from __future__ import annotations

import httpx

from src.fetch_text import ArticleFetcher, looks_like_pdf


class FakeUjin:
    def __init__(self, text: str) -> None:
        self.text = text
        self.seen: list[str] = []

    def scrape(self, url, *, mode="article", force_refresh=False):
        self.seen.append(url)

        class R:
            pass

        r = R()
        r.text = self.text
        return r


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_looks_like_pdf():
    assert looks_like_pdf("https://x.org/a.pdf")
    assert looks_like_pdf("https://onlinelibrary.wiley.com/doi/pdfdirect/10.1/x")
    assert looks_like_pdf("https://x.org/article/pdf/123")
    assert not looks_like_pdf("https://x.org/doi/10.1/abc")
    assert not looks_like_pdf("")


def test_pdf_url_uses_pdf_extractor():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 binary...", headers={"content-type": "application/pdf"})

    fetcher = ArticleFetcher(
        ujin=FakeUjin("html body"),
        http_client=_http(handler),
        pdf_extractor=lambda b: "extracted pdf text " * 40,
    )
    out = fetcher.fetch("https://pub.example/doi/pdfdirect/10.1/x")
    assert out.startswith("extracted pdf text")
    assert fetcher._ujin.seen == []  # HTML path not needed


def test_html_url_uses_ujin():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not called
        return httpx.Response(404)

    ujin = FakeUjin("a substantial html article body " * 30)
    fetcher = ArticleFetcher(ujin=ujin, http_client=_http(handler))
    out = fetcher.fetch("https://pub.example/doi/10.1/abc")
    assert "html article body" in out
    assert ujin.seen == ["https://pub.example/doi/10.1/abc"]


def test_falls_back_to_pdf_when_html_short():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    # ujin (HTML primary) returns too little -> fetcher tries the PDF path.
    fetcher = ArticleFetcher(
        ujin=FakeUjin("tiny"),
        http_client=_http(handler),
        pdf_extractor=lambda b: "long pdf body " * 50,
        min_chars=400,
    )
    out = fetcher.fetch("https://pub.example/doi/10.1/abc")  # not pdf-looking
    assert out.startswith("long pdf body")


def test_non_pdf_content_type_returns_empty_pdf():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>paywall</html>", headers={"content-type": "text/html"})

    # PDF-looking URL but server returns HTML, and no ujin -> nothing usable.
    fetcher = ArticleFetcher(ujin=None, http_client=_http(handler), pdf_extractor=lambda b: "x")
    assert fetcher.fetch("https://pub.example/a.pdf") == ""


def test_http_error_is_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    fetcher = ArticleFetcher(ujin=None, http_client=_http(handler))
    assert fetcher.fetch("https://pub.example/a.pdf") == ""
