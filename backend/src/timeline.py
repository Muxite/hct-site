"""Build the small "Latest" timeline: the N most recent publications + a blurb.

Scholar profiles only give us a publication *year*, so the timeline is
year-based (``date_label`` = the year) — we don't fabricate a day/month. Each
entry gets a short AI blurb in the lab's voice (reusing the describe step).
"""

from __future__ import annotations

from typing import Any, Protocol

from src.describe import describe_publication
from src.models import Publication, PublicationSet, TimelineEntry


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


def most_recent(pubs: list[Publication], n: int = 5) -> list[Publication]:
    """Return the ``n`` newest publications (by year desc, then title)."""

    return sorted(pubs, key=lambda p: (-p.year, p.title.lower()))[:n]


def build_timeline(
    ps: PublicationSet,
    *,
    llm: SupportsComplete | None = None,
    style_profile: str = "",
    describe_system: str | None = None,
    n: int = 5,
) -> list[TimelineEntry]:
    """Build up to ``n`` timeline entries from the publication set.

    If ``llm`` is given, a fresh blurb is written for each entry; otherwise the
    paper's existing ``description`` (if any) is reused and no LLM is called.
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
