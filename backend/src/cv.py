"""CV files as the *primary* publication source of truth.

A lab member's CV (``.docx``/``.txt``/``.md``/``.tex``, dropped into the
mounted inbox/inputs folder) is the document the lab actually keeps up to
date, so it outranks Google Scholar: on duplicate papers (same deterministic
slug) the CV's metadata wins — the orchestrator merges CV-derived sources
first and dedupe keeps the first occurrence.

Extraction is deterministic-first: the publications section is split into
individual entries and each is parsed with plain heuristics
(:mod:`src.cv_parse`). Only the entries the heuristics can't fill confidently
are sent to the LLM — one small per-entry call through the normal
``extract -> validate -> repair`` path — so a structurally stable CV costs
zero LLM tokens. Every entry's outcome (deterministic / llm / failed) is
recorded on a :class:`~src.metrics.ParseTracker` for the run report.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.cv_parse import parse_cv_entries
from src.extract import ExtractionError, extract_publications
from src.models import PublicationSet
from src.style import read_text_input

# Headings that start the publications part of a CV, tried in order. The UBC
# faculty CV appends a "Publications Record" form; plainer CVs just have a
# "Publications" heading. Everything from the first match to the end of the
# document is kept — what follows (books, patents, artistic works, work in
# progress) is still publication-flavored and parses/extracts fine.
_SECTION_PATTERNS = (
    r"publications\s+record",
    r"refereed\s+publications",
    r"^\s*publications\b",
)


def read_cv_text(path: str | Path) -> str:
    """Read a CV document to plain text (delegates to the style reader)."""

    return read_text_input(path)


def publications_section(text: str) -> str:
    """Trim CV text to its publications section (heading -> end of document).

    Falls back to the full text when no known heading is found, so an unusual
    CV layout degrades to "extract from everything" instead of silently
    yielding nothing.
    """

    for pat in _SECTION_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            return text[m.start() :].strip()
    return text.strip()


def extract_cv_publications(
    cv_text: str,
    *,
    llm: Any,
    system_prompt: str | None = None,
    examples: str = "",
    parse_tracker: Any | None = None,
) -> PublicationSet:
    """Extract every publication from a CV, deterministic-first.

    1. Trim to the publications section and split it into entries.
    2. Parse each entry with the :mod:`src.cv_parse` heuristics.
    3. Only failed entries go to the LLM — one entry per call through the
       normal :func:`~src.extract.extract_publications` path (validation +
       one repair retry). Entries the LLM can't fix either are dropped.
    4. Every outcome is recorded on ``parse_tracker`` (when given); the
       merged result is deduped by slug, so an entry duplicated across the
       CV's own subsections collapses too.
    """

    section = publications_section(cv_text)
    pubs, failed_entries, outcomes = parse_cv_entries(section)
    merged = PublicationSet(publications=list(pubs))

    # Per-entry LLM fallback: ~one paper of text per call, so the prompt is
    # tiny and a failure only loses that single entry.
    fallback_iter = iter(failed_entries)
    for outcome in outcomes:
        if outcome.path != "failed":
            if parse_tracker is not None:
                parse_tracker.record(outcome)
            continue
        entry = next(fallback_iter)
        try:
            ps = extract_publications(
                entry.text, llm=llm, system_prompt=system_prompt, examples=examples
            )
        except ExtractionError as e:
            outcome.error = f"{outcome.error}; llm fallback failed: {e}"
        else:
            if ps.publications:
                merged.publications.extend(ps.publications)
                outcome.path = "llm"
                outcome.slug = ps.publications[0].id
                outcome.error = None
            else:
                outcome.error = f"{outcome.error}; llm fallback returned no entries"
        if parse_tracker is not None:
            parse_tracker.record(outcome)

    return merged.deduped()
