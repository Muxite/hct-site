"""Migrate the static site's content into Supabase rows.

The People and Research sections are regular tile markup, so we parse them into
``Person`` / ``ResearchProject`` rows. The remaining prose sections (vision,
innovation, contact, ...) become ``site_content`` key/value blurbs the frontend
can fetch by key. Where the source is thin (blank research taglines), the AI can
fill a short ``description``; this is optional so the parser stays testable
without an LLM.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Protocol

from src.models import Person, ResearchProject, SiteContent


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


# Prose <h2> sections we lift verbatim into site_content (heading -> key).
# People/Research/Publications are structured and handled separately.
_SECTION_KEYS = {
    "vision": "vision",
    "innovation": "innovation",
    "contact": "contact",
    "land acknowledgment": "land_acknowledgment",
    "equity, diversity, inclusion + indigeneity": "edi",
    "sponsors": "sponsors",
    "opportunities": "opportunities",
}
_SKIP_HEADINGS = {"people", "research", "publications"}

_RESEARCH_DESC_SYSTEM = (
    "You write a single 1-2 sentence description of a research project for a lab "
    "website, in the lab's voice. Plain text, no heading. Use only the given "
    "title and tagline; never invent specifics."
)


def _clean(text: str) -> str:
    """Unescape entities, collapse whitespace, trim."""
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _strip_tags(fragment: str) -> str:
    """Plain text of an HTML fragment (drop scripts/tags, keep readable text)."""
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", fragment, flags=re.DOTALL | re.I)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</(p|div|li|h[1-6])>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = _html.unescape(text)
    # Collapse runs of spaces but keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _section(html: str, anchor: str) -> str:
    """Return the substring from ``anchor`` up to the next top-level ``<h2``."""
    start = html.find(anchor)
    if start == -1:
        return ""
    rest = html[start:]
    nxt = re.search(r"<h2[\s>]", rest[len(anchor):])
    return rest if not nxt else rest[: len(anchor) + nxt.start()]


def parse_people(html: str) -> list[Person]:
    """Extract lab members from the ``#people`` tile section."""
    section = _section(html, 'id="people"')
    people: list[Person] = []
    for i, chunk in enumerate(section.split('class="person-tile"')[1:]):
        photo = re.search(r'<img[^>]*\bsrc="([^"]+)"', chunk)
        name = re.search(r"<strong>(.*?)</strong>", chunk, re.DOTALL)
        role = re.search(r'class="project"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        email = re.search(r'class="email">.*?<a[^>]*>(.*?)</a>', chunk, re.DOTALL)
        if not name:
            continue
        people.append(
            Person(
                name=_clean(name.group(1)),
                role=_clean(role.group(1)) if role else None,
                email=_clean(email.group(1)).replace(" [at] ", "@") if email else None,
                photo=_clean(photo.group(1)) if photo else None,
                sort_order=i,
            )
        )
    return people


def parse_research(html: str) -> list[ResearchProject]:
    """Extract research projects from the ``#research`` tile section."""
    section = _section(html, 'id="research"')
    projects: list[ResearchProject] = []
    for i, chunk in enumerate(section.split('class="research-tile"')[1:]):
        link = re.search(r'href="([^"]+)"', chunk)
        image = re.search(r'<img[^>]*\bsrc="([^"]+)"', chunk)
        title = re.search(r"<h3>(.*?)</h3>", chunk, re.DOTALL)
        tagline = re.search(r"<h4[^>]*>(.*?)</h4>", chunk, re.DOTALL)
        if not title:
            continue
        tag = _clean(tagline.group(1)) if tagline else ""
        projects.append(
            ResearchProject(
                title=_clean(title.group(1)),
                tagline=tag or None,
                link=_clean(link.group(1)) if link else None,
                image=_clean(image.group(1)) if image else None,
                sort_order=i,
            )
        )
    return projects


def parse_site_sections(html: str) -> list[SiteContent]:
    """Lift the prose ``<h2>`` sections into site_content key/value blurbs."""
    out: list[SiteContent] = []
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL):
        heading = _clean(m.group(1)).lower()
        if heading in _SKIP_HEADINGS:
            continue
        key = _SECTION_KEYS.get(heading)
        if not key:
            continue
        body = html[m.end():]
        nxt = re.search(r"<h2[\s>]", body)
        text = _strip_tags(body[: nxt.start()] if nxt else body)
        if text:
            out.append(SiteContent(key=key, value={"title": _clean(m.group(1)), "text": text}))
    return out


def publications_block_text(html: str) -> str:
    """Plain text of the static ``#publications-static`` fallback block.

    The block lists the lab's papers (newest first) and is the offline source for
    `import-html` when Google Scholar is unreachable. Returns "" if absent. The
    caller caps length (the recent slice) when feeding it to the LLM.
    """
    start = html.find('id="publications-static"')
    if start == -1:
        return ""
    block = html[start:].split("</main>")[0]
    # Inline anchor hrefs as "text (url)" BEFORE stripping tags — otherwise the
    # DOI/links (which live in href, not the link text) are lost and every
    # extracted paper ends up with link=null.
    block = re.sub(
        r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", block, flags=re.I | re.S
    )
    return _strip_tags(block)


def enrich_research(
    projects: list[ResearchProject],
    *,
    llm: SupportsComplete,
    style_profile: str = "",
) -> None:
    """Write a short ``description`` for each project (in place) via the LLM."""
    for p in projects:
        style = f"Lab style:\n{style_profile.strip()}\n\n" if style_profile.strip() else ""
        user = f"{style}Project title: {p.title}\nTagline: {p.tagline or '(none)'}\n\nWrite the description."
        p.description = llm.complete(
            system=_RESEARCH_DESC_SYSTEM, user=user, json_mode=False,
            max_tokens=200, label="research",
        ).strip()


def build_content(
    html: str,
    *,
    llm: SupportsComplete | None = None,
    style_profile: str = "",
) -> tuple[list[Person], list[ResearchProject], list[SiteContent]]:
    """Parse the static HTML into rows; optionally enrich research via the LLM."""
    people = parse_people(html)
    research = parse_research(html)
    site_content = parse_site_sections(html)
    if llm is not None:
        enrich_research(research, llm=llm, style_profile=style_profile)
    return people, research, site_content
