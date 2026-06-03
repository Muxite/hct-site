"""Thin HTTP client for the ujin scrape service (`POST /scrape`).

ujin is treated as a black box: we send a URL, it handles the
HTTP -> obscura -> sitemap -> RSS fallback chain and returns a normalized
payload with a stable ``fingerprint`` (for change detection) and the page
content. We pull a best-effort text blob for the LLM and pass the rest through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class ScrapeResult:
    """Normalized view of a ujin ``/scrape`` response."""

    url: str
    kind: str  # links | article | structured | empty | error
    fingerprint: str  # SHA-256 of normalized payload; "" on empty/error
    text: str  # best-effort text for the LLM (article body or link list)
    used_renderer: bool  # True when obscura (headless) was used
    strategy_used: str  # http | obscura | sitemap_news | rss | cache | ...
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.kind not in ("error", "") and bool(self.text)


def _extract_text(data: dict[str, Any]) -> str:
    """Pull the most useful text from a scrape response, by mode/kind."""

    article = data.get("article")
    if article and article.get("text"):
        title = (article.get("title") or "").strip()
        body = article["text"].strip()
        return f"{title}\n\n{body}".strip()

    structured = data.get("structured")
    if structured:
        import json

        return json.dumps(structured, ensure_ascii=False, indent=2)

    links = data.get("links") or []
    if links:
        return "\n".join(
            f"- {(l.get('text') or '').strip()} ({(l.get('url') or '').strip()})"
            for l in links
        )
    return ""


class UjinClient:
    """Client for the ujin scrape service.

    Pass a pre-built ``httpx.Client`` (e.g. with a MockTransport) for testing;
    otherwise one is created against ``base_url``.
    """

    def __init__(
        self,
        base_url: str = "http://ujin:8901",
        *,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self._base, timeout=timeout)

    def scrape(
        self, url: str, *, mode: str = "article", force_refresh: bool = False
    ) -> ScrapeResult:
        """Scrape ``url`` and return a normalized result.

        ``mode`` is passed straight through to ujin (``article`` for body text,
        ``links`` for a headline link-set, ``structured`` for JSON-LD/OG, etc.).
        """

        resp = self._client.post(
            "/scrape",
            json={"url": url, "mode": mode, "force_refresh": force_refresh},
        )
        resp.raise_for_status()
        data = resp.json()
        return ScrapeResult(
            url=data.get("url", url),
            kind=data.get("kind", ""),
            fingerprint=data.get("fingerprint", ""),
            text=_extract_text(data),
            used_renderer=bool(data.get("used_renderer", False)),
            strategy_used=data.get("strategy_used", ""),
            raw=data,
        )

    def health(self) -> bool:
        """Return True if the scrape service reports healthy."""

        try:
            resp = self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "UjinClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
