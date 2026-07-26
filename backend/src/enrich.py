"""Fill OpenAlex-derived fields onto publications — free, no LLM involved.

``hct-manager enrich`` walks every publication still missing at least one of
``citation_count`` / ``concepts`` / ``oa_status``, asks
:meth:`~src.paper_sources.PaperSources.discover` for the best-matched OpenAlex
record — the same lookup already used for paper-sample generation
(``paper_samples.py``), so this adds no new API surface — and writes only the
fields that are both (a) yielded by a *matched* OpenAlex record and (b) still
null on that row. Each field is its own PATCH filtered on ``slug`` +
``<field>: is.null``: the null-check runs server-side, so this can never race
with (or clobber) a value an admin or an earlier run already set — exactly
the fill-if-empty discipline ``sync_content._fill_if_empty`` established.

A record matched via Crossref (or no record at all) contributes nothing:
Crossref carries none of these fields (see ``paper_sources.parse_crossref_work``),
and an unmatched/weak search result is rejected the same way link discovery
already rejects it elsewhere — attaching a wrong paper's citation count would
be worse than leaving the column empty.

OpenAlex is free and keyless (generous "polite pool" rate limits), so this is
safe to run across the *entire* publication archive — unlike the LLM-cost
describe/summarize commands, which are deliberately scoped to a subset.
"""

from __future__ import annotations

import re
from typing import Any

from src.paper_sources import PaperSources

# The three publications columns this command may ever write, and only where
# each is individually still null on a given row — see enrich_publications.
ENRICH_FIELDS = ("citation_count", "concepts", "oa_status")

# PostgREST 'or' filter: fetch only rows missing at least one of the three
# fields, so a routine re-run doesn't even read back publications that are
# already fully enriched (let alone call discover() for them).
_MISSING_FILTER = "(citation_count.is.null,concepts.is.null,oa_status.is.null)"

# A publications.link that is itself a DOI redirect (the common case for a
# CV-sourced link). Anything else (a bare publisher/landing-page URL) must
# NOT be handed to discover() as `doi=` — PaperSources.discover trusts any
# non-empty `doi` outright as "the known DOI", so a non-DOI link there would
# produce a bogus doi:<url> lookup instead of a real title search.
_DOI_URL_RE = re.compile(r"^https?://(dx\.)?doi\.org/(?P<doi>10\.\S+)$", re.IGNORECASE)


def _doi_from_link(link: str | None) -> str | None:
    """The bare DOI if ``link`` is a doi.org redirect URL, else ``None``."""

    if not link:
        return None
    m = _DOI_URL_RE.match(link.strip())
    return m.group("doi") if m else None


def _discover_fields(row: dict[str, Any], sources: PaperSources) -> dict[str, Any]:
    """Look up one publication and return whichever enrichment fields it yields.

    Empty when there's no title to search on, discovery didn't confidently
    match, or the matched record came from Crossref (which carries none of
    these fields).
    """

    title = (row.get("title") or "").strip()
    if not title:
        return {}
    result = sources.discover(
        title=title,
        authors=row.get("authors") or None,
        year=row.get("year"),
        doi=_doi_from_link(row.get("link")),
    )
    rec = result.record
    if not result.matched or rec is None or rec.source != "openalex":
        return {}

    values: dict[str, Any] = {}
    if rec.citation_count is not None:
        values["citation_count"] = rec.citation_count
    if rec.concepts:
        values["concepts"] = rec.concepts
    oa_status = ((rec.raw or {}).get("open_access") or {}).get("oa_status")
    if oa_status:
        values["oa_status"] = oa_status
    return values


def enrich_publications(
    supabase: Any, sources: PaperSources, *, limit: int | None = None
) -> int:
    """Fill missing OpenAlex fields across publications. Returns rows touched.

    Only ever writes a field that is both discovered and still null on that
    row: each write is its own ``is.null``-filtered PATCH (see module
    docstring), never a read-then-write. A publication already fully enriched
    is skipped before any ``discover()`` call is made — no wasted lookups on
    a routine re-run. ``limit`` caps how many publications get *written to*
    this run (matching ``describe``/``summarize``'s convention), not how many
    are scanned.
    """

    rows = supabase.select(
        "publications",
        columns="slug,title,authors,year,link,citation_count,concepts,oa_status",
        params={"or": _MISSING_FILTER},
    )
    written = 0
    for row in rows:
        if limit is not None and written >= limit:
            break
        missing = [f for f in ENRICH_FIELDS if row.get(f) is None]
        if not missing:
            continue  # already fully enriched

        values = _discover_fields(row, sources)
        wrote_any = False
        for field in missing:
            value = values.get(field)
            if value is None:
                continue
            supabase.update(
                "publications",
                {field: value},
                params={"slug": f"eq.{row['slug']}", field: "is.null"},
            )
            wrote_any = True
        if wrote_any:
            written += 1
    return written
