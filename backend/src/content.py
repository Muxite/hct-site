"""Site boilerplate -> ``site_content`` rows (plus the QA text helpers).

The free-text sections (vision, innovation, contact, ...) and the header/nav
come from an editable ``site.yaml`` dropped into the mounted inbox folder and
become ``site_content`` key/value blurbs the frontend fetches by key (see
:func:`load_site_yaml`). People and research are likewise YAML-driven (see
:mod:`src.sync_content`). ``parse_site_sections`` survives only as a legacy
HTML migration path; ``publications_block_text`` survives for the QA
cross-check and the experiment harness.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

import yaml

from src.models import SiteContent

# Prose section keys we accept in site.yaml (also the legacy <h2> heading map
# below). ``site_meta`` holds the header/nav and is emitted alongside these.
_SITE_META_KEY = "site_meta"


class SiteContentError(ValueError):
    """Raised when ``site.yaml`` is missing, malformed, or invalid."""


def leading_comment_block(path: str | Path) -> str:
    """Return the file's leading ``#`` comment + blank-line header (or "").

    Lets the round-trip writers (people/research/site) rewrite the body while
    keeping the hand-authored "edit this then run sync-content" preamble.
    """
    p = Path(path)
    if not p.exists():
        return ""
    kept: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip() == "" or line.lstrip().startswith("#"):
            kept.append(line)
        else:
            break
    text = "\n".join(kept).rstrip("\n")
    return text + "\n\n" if text else ""


def dump_yaml_with_header(path: str | Path, data: dict) -> None:
    """Write ``data`` as block-style YAML, preserving the file's comment header.

    ``width`` is set very wide so long taglines / prose stay on one line instead
    of being folded, keeping the diff against a hand-edited file readable.
    """
    header = leading_comment_block(path)
    body = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    Path(path).write_text(header + body, encoding="utf-8")


def load_site_yaml(path: str | Path) -> list[SiteContent]:
    """Parse ``site.yaml`` into ``site_content`` rows.

    Emits one row per ``sections.<key>`` (value ``{title, text}``) plus a
    ``site_meta`` row holding ``{title, subtitle, tagline, nav}`` from the
    top-level ``site:`` block. The YAML is the source of truth for the boilerplate.
    """

    p = Path(path)
    if not p.exists():
        raise SiteContentError(f"{p} not found")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SiteContentError(f"{p}: expected a top-level mapping")

    out: list[SiteContent] = []

    meta = data.get("site")
    if meta is not None:
        if not isinstance(meta, dict):
            raise SiteContentError(f"{p}: 'site:' must be a mapping")
        out.append(SiteContent(key=_SITE_META_KEY, value=dict(meta)))

    sections = data.get("sections") or {}
    if not isinstance(sections, dict):
        raise SiteContentError(f"{p}: 'sections:' must be a mapping")
    for key, value in sections.items():
        if not isinstance(value, dict):
            raise SiteContentError(f"{p}: sections['{key}'] must be a mapping")
        text = str(value.get("text", "")).strip()
        if not text:
            raise SiteContentError(f"{p}: sections['{key}'] has empty 'text'")
        title = str(value.get("title", key)).strip()
        out.append(SiteContent(key=str(key), value={"title": title, "text": text}))

    if not out:
        raise SiteContentError(f"{p}: no 'site:' or 'sections:' content found")
    return out


def dump_site_yaml(path: str | Path, contents: list[SiteContent]) -> None:
    """Write ``site_content`` rows back to ``site.yaml`` (inverse of load).

    The ``site_meta`` row becomes the top-level ``site:`` block; every other row
    becomes ``sections.<key>``. Header comment is preserved. Re-loading the
    written file yields the same rows (round-trip safe).
    """
    site_meta: dict = {}
    sections: dict = {}
    for c in contents:
        if c.key == _SITE_META_KEY:
            site_meta = dict(c.value)
        else:
            sections[c.key] = dict(c.value)

    data: dict = {}
    if site_meta:
        data["site"] = site_meta
    if sections:
        data["sections"] = sections
    dump_yaml_with_header(path, data)

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

    The block lists the lab's papers (newest first); the QA source cross-check
    and the experiment harness read it. Returns "" if absent.
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
