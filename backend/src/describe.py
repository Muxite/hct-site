"""Opt-in description writing: give each paper a short, lab-voice ``description``.

This is deliberately *decoupled* from extraction. Extraction (``extract.py``)
runs on a Scholar **profile** page — a bare list with no abstracts — so it can't
write good descriptions and never tries. Description writing is a separate step
the operator runs on demand (``hct-manager describe``): it reads the already
extracted ``publications.yaml``, optionally fetches each paper's own page for
grounding, and asks the LLM to write one short blurb in the lab's voice (the
saved style profile). Keeping it separate means the common extraction run pays
no style-profile or description tokens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from src.models import Publication, PublicationSet

_DEFAULT_DESCRIBE_SYSTEM = (
    "You write a single short description of one academic paper for the paper's "
    "page on a research lab's website, in the lab's voice. 2-3 sentences, plain "
    "text, no title or citation repeated back. When source text from the paper's "
    "page is provided, condense and paraphrase it into a shorter, plainer version "
    "(shorten, do not embellish); otherwise stay general. Describe what the work "
    "does and why it matters; never invent results, numbers, or claims not "
    "supported by what you are given."
)


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


def load_describe_system_prompt(templates_dir: str | Path | None) -> str:
    """Load the describe system prompt from a template file, else default."""

    if templates_dir:
        p = Path(templates_dir) / "describe_system.txt"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return _DEFAULT_DESCRIBE_SYSTEM


def build_describe_prompt(
    pub: Publication, *, style_profile: str = "", source_text: str = ""
) -> str:
    """Build the user prompt for describing a single publication."""

    parts: list[str] = []
    if style_profile.strip():
        parts.append(f"Write in this lab's style:\n{style_profile.strip()}\n")
    facts = [
        f"Title: {pub.title}",
        f"Authors: {'; '.join(pub.authors)}",
        f"Year: {pub.year}",
        f"Type: {pub.type.value}",
    ]
    if pub.venue:
        facts.append(f"Venue: {pub.venue}")
    parts.append("Paper:\n" + "\n".join(facts))
    if source_text.strip():
        parts.append(
            "\nSource text from the paper's page (use only this for facts):\n"
            f"{source_text.strip()}"
        )
    parts.append("\nWrite the description now.")
    return "\n".join(parts)


def describe_publication(
    pub: Publication,
    *,
    llm: SupportsComplete,
    system_prompt: str | None = None,
    style_profile: str = "",
    source_text: str = "",
    max_source_chars: int = 6000,
    label: str = "describe",
) -> str:
    """Return a short lab-voice description for one paper (free text).

    Output is capped low (``max_tokens``) — the description is only 2-3
    sentences, so there is no reason to pay for more. ``label`` tags the metrics
    record (e.g. ``describe`` vs ``timeline``).
    """

    system = system_prompt if system_prompt is not None else _DEFAULT_DESCRIBE_SYSTEM
    user = build_describe_prompt(
        pub,
        style_profile=style_profile,
        source_text=source_text.strip()[:max_source_chars],
    )
    return llm.complete(
        system=system, user=user, json_mode=False, max_tokens=256, label=label
    ).strip()


def describe_set(
    ps: PublicationSet,
    *,
    llm: SupportsComplete,
    system_prompt: str | None = None,
    style_profile: str = "",
    fetch: Callable[[str], str] | None = None,
    only_missing: bool = True,
    limit: int | None = None,
) -> int:
    """Fill ``description`` on publications in-place. Returns the count written.

    ``fetch`` (optional) maps a paper ``link`` to grounding text (e.g. the ujin
    scrape of that page); when absent, descriptions are written from the
    metadata alone. ``only_missing`` skips papers that already have a
    description; ``limit`` caps how many are written this run.
    """

    written = 0
    for pub in ps.publications:
        if limit is not None and written >= limit:
            break
        if only_missing and pub.description and pub.description.strip():
            continue
        source_text = ""
        if fetch and pub.link:
            try:
                source_text = fetch(pub.link) or ""
            except Exception:  # noqa: BLE001 — grounding is best-effort
                source_text = ""
        pub.description = describe_publication(
            pub,
            llm=llm,
            system_prompt=system_prompt,
            style_profile=style_profile,
            source_text=source_text,
        )
        written += 1
    return written
