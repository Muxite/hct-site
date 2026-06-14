"""Build the timeline: the lab's publication history, newest first, + a blurb.

By default this is the *full* chronological history (every publication, ordered
year-desc) — the centerpiece of the site, grouped by year in the frontend. Pass
``n`` to cap it (e.g. a short "Latest" strip). The CV / Scholar only give us a
publication *year*, so the timeline is year-based (``date_label`` = the year) —
we don't fabricate a day/month. Each entry can carry a short blurb in the lab's
voice; in a normal ``run`` we reuse any saved ``description`` rather than calling
the LLM for every historical paper (the ``describe`` step fills those).
"""

from __future__ import annotations

from typing import Any, Protocol

from src.describe import describe_publication
from src.models import Publication, PublicationSet, TimelineEntry


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


def most_recent(pubs: list[Publication], n: int | None = None) -> list[Publication]:
    """Return publications newest first (by year desc, then title).

    With ``n=None`` the *whole* set is returned (the full history); pass an
    integer to cap it to the ``n`` newest.
    """

    ordered = sorted(pubs, key=lambda p: (-p.year, p.title.lower()))
    return ordered if n is None else ordered[:n]


def build_timeline(
    ps: PublicationSet,
    *,
    llm: SupportsComplete | None = None,
    style_profile: str = "",
    describe_system: str | None = None,
    n: int | None = None,
) -> list[TimelineEntry]:
    """Build timeline entries from the publication set, newest first.

    With ``n=None`` (the default) this is the full publication history; pass an
    integer to cap it. If ``llm`` is given, a fresh blurb is written for each
    entry; otherwise the paper's existing ``description`` (if any) is reused and
    no LLM is called.
    """

    entries: list[TimelineEntry] = []
    for i, pub in enumerate(most_recent(ps.publications, n)):
        blurb = pub.description or None
        if llm is not None:
            blurb = describe_publication(
                pub,
                llm=llm,
                system_prompt=describe_system,
                style_profile=style_profile,
                label="timeline",
            )
        entries.append(
            TimelineEntry(
                slug=pub.id,
                title=pub.title,
                authors=list(pub.authors),
                year=pub.year,
                date_label=str(pub.year),
                blurb=blurb,
                position=i,
            )
        )
    return entries
