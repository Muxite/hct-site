"""Google Scholar URL/mode helpers (hct side — *not* inside ujin).

ujin stays a black box with no Scholar-specific logic; the Scholar quirks we do
need live here. Empirically (see ``experiments/`` notes):

* A Scholar **profile** page is *not* IP-blocked over plain HTTP — but it is a
  *table* of publications, so ``mode="article"`` (readability) returns nothing.
  ``mode="links"`` returns every paper's title + ``view_citation`` URL.
* Scholar paginates the profile at 20 rows; ``&pagesize=100`` returns the whole
  list in one HTTP fetch (no headless renderer needed).
* The per-paper ``view_citation`` pages *are* protected (HTTP 502; even the
  obscura renderer gets an empty/consent wall), so authors/venue/year are not
  reachable from Scholar — they come from the CV (the primary source) instead.

So for a profile source we force ``mode="links"`` and normalize the URL to ask
for a full page. This turns the previously-empty scrape into the complete title
list (useful for change detection); it does **not** by itself yield the metadata
the publication schema requires.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

#: Scholar caps a citations profile around 100 rows per page; ask for the max.
DEFAULT_PAGESIZE = 100


def is_scholar_profile(url: str) -> bool:
    """True if ``url`` is a Google Scholar *citations profile* page."""

    p = urlparse(url)
    if "scholar.google." not in p.netloc:
        return False
    q = dict(parse_qsl(p.query))
    # A profile page is /citations with a ``user`` id and no per-paper view.
    return p.path.endswith("/citations") and "user" in q and "citation_for_view" not in q


def normalize_profile_url(url: str, *, pagesize: int = DEFAULT_PAGESIZE) -> str:
    """Return a profile URL set up for a full, newest-first render (idempotent).

    Forces ``hl=en``, ``pagesize`` (whole list in one fetch), and
    ``view_op=list_works&sortby=pubdate`` so the rows come back newest-first —
    which is what the timeline + change detection want. Non-Scholar-profile URLs
    are returned unchanged.
    """

    if not is_scholar_profile(url):
        return url
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q.setdefault("hl", "en")
    q["pagesize"] = str(pagesize)
    q["view_op"] = "list_works"
    q["sortby"] = "pubdate"
    return urlunparse(p._replace(query=urlencode(q)))


def scrape_mode_for(url: str, fallback: str) -> str:
    """``links`` for a Scholar profile (a table, not an article); else ``fallback``."""

    return "links" if is_scholar_profile(url) else fallback


def page_url(url: str, cstart: int, pagesize: int = DEFAULT_PAGESIZE) -> str:
    """Profile URL for one pagination slice: rows ``[cstart, cstart+pagesize)``.

    The "Show more" button is just UI for the ``cstart`` GET param, so we page
    through a profile by walking ``cstart`` (0, pagesize, 2*pagesize, …) until a
    slice comes back short/empty. Newest-first (``sortby=pubdate``).
    """

    base = normalize_profile_url(url, pagesize=pagesize)
    if not is_scholar_profile(url):
        return base
    p = urlparse(base)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q["cstart"] = str(max(0, int(cstart)))
    return urlunparse(p._replace(query=urlencode(q)))
