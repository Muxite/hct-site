"""Fetch an article's body text from a URL, handling PDFs and HTML.

The paper-summary experiment needs the open-access full text to give RAG
something substantial to chunk. ujin extracts HTML article bodies well but does
not read PDFs, and most of this lab's open-access links are publisher PDFs
(Wiley ``pdfdirect``, etc.). :class:`ArticleFetcher` routes by URL: PDF-looking
links are downloaded and text-extracted with pypdf (the ``backend[rag]`` extra),
everything else goes through ujin; each path falls back to the other if it comes
up short. The PDF extractor is injectable so the routing is unit-tested without a
real PDF.
"""

from __future__ import annotations

import io
import re

import httpx

# Heuristic: URLs that are almost certainly a PDF download.
_PDF_HINTS = ("pdfdirect", "/pdf/", "/pdf?", "type=printable", "downloadpdf")


def looks_like_pdf(url: str) -> bool:
    if not url:
        return False
    u = url.lower().split("?")[0]
    if u.endswith(".pdf"):
        return True
    return any(h in url.lower() for h in _PDF_HINTS)


def extract_pdf_text(content: bytes, *, max_pages: int = 30) -> str:
    """Extract text from PDF bytes using pypdf (lazy import, [rag] extra)."""

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only off the [rag] extra
        raise RuntimeError(
            "pypdf is not installed; run `pip install -e 'backend[rag]'` to read PDFs"
        ) from exc
    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a bad page should not sink the whole doc
            continue
    text = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class ArticleFetcher:
    """Fetch article body text, routing PDF vs HTML and falling back across both."""

    def __init__(
        self,
        *,
        ujin=None,
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
        pdf_extractor=None,
        min_chars: int = 400,
    ) -> None:
        self._ujin = ujin
        self._http = http_client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "hct-manager/0.1 (paper summaries)"},
        )
        self._pdf = pdf_extractor or extract_pdf_text
        self._min = min_chars

    def fetch(self, url: str) -> str:
        """Return the best body text for ``url`` ("" on failure)."""

        if not url:
            return ""
        pdf_first = looks_like_pdf(url)
        primary = self._fetch_pdf(url) if pdf_first else self._fetch_html(url)
        if len(primary) >= self._min:
            return primary
        # Primary came up short; try the other path and keep whichever is longer.
        secondary = self._fetch_html(url) if pdf_first else self._fetch_pdf(url)
        return secondary if len(secondary) > len(primary) else primary

    def _fetch_pdf(self, url: str) -> str:
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            return ""
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or resp.content[:5] == b"%PDF-":
            try:
                return self._pdf(resp.content)
            except Exception:  # noqa: BLE001 - extraction is best-effort
                return ""
        return ""

    def _fetch_html(self, url: str) -> str:
        if self._ujin is None:
            return ""
        try:
            return self._ujin.scrape(url, mode="article").text or ""
        except Exception:  # noqa: BLE001 - scraping is best-effort
            return ""

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ArticleFetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
