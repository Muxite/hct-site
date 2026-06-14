"""Turn scraped page text into a validated :class:`PublicationSet` via the LLM.

Flow: build the prompt (system template + optional few-shot examples) -> call
the LLM (JSON mode) -> parse JSON -> compute stable ids -> validate against the
schema. If parsing or validation fails, do exactly one repair round-trip (a
compact correction that feeds back only the bad output + error, not the page),
then give up with a clear error.

Token notes: extraction never writes descriptions (that is a separate opt-in
step, see ``describe.py``), so no style profile is sent here. The page text is
capped (``max_page_chars``) and the repair round-trip does not resend it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from src.models import Publication, PublicationSet, slug_for

# Embedded fallback if the template file is missing (keeps tests/standalone runs working).
_DEFAULT_SYSTEM = (
    "Extract the publication list from the page text and return ONLY a JSON "
    'object {"publications": [{"title","authors","year","type","venue","link"}]}. '
    'Always set description to null. Do not include an "id" field. Output JSON only.'
)

# Default cap on page text length sent to the LLM. Scholar pages are mostly
# boilerplate (nav, sidebars, "cited by", footers); the publication list sits
# near the top, so a generous cap trims tail noise without losing entries.
DEFAULT_MAX_PAGE_CHARS = 16000

# Output budget for the JSON publication list. The client default (4096) is far
# too small: a real profile is dozens of papers, and pretty-printed JSON for ~30
# papers already overruns 4096 completion tokens, so the first pass was *always*
# truncated mid-object and *always* forced the repair retry (doubling cost +
# latency). Gemini Flash bills only the tokens it emits, so a high cap is free
# until used. Sized for a large profile (100+ papers).
DEFAULT_MAX_OUTPUT_TOKENS = 16384


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


class ExtractionError(RuntimeError):
    """Raised when the LLM output cannot be parsed/validated even after repair."""


def load_system_prompt(templates_dir: str | Path | None) -> str:
    """Load the extraction system prompt from a template file, else default."""

    if templates_dir:
        path = Path(templates_dir) / "extraction_system.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return _DEFAULT_SYSTEM


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from LLM text, tolerating ``` fences / surrounding prose."""

    text = text.strip()
    # Strip markdown fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost { ... } span.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no JSON object found", text, 0)


def build_user_prompt(
    page_text: str, *, examples: str = "", max_page_chars: int = DEFAULT_MAX_PAGE_CHARS
) -> str:
    parts: list[str] = []
    if examples.strip():
        parts.append(f"Examples of good extractions:\n{examples.strip()}\n")
    page = page_text.strip()[:max_page_chars]
    parts.append(
        "Extract all publications from the following page text:\n\n"
        "<<<PAGE>>>\n" + page + "\n<<<END>>>"
    )
    return "\n".join(parts)


def parse_publication_set(raw_text: str, *, fingerprints: dict[str, str] | None = None) -> PublicationSet:
    """Parse + validate LLM JSON into a PublicationSet (ids computed here)."""

    obj = _extract_json_object(raw_text)
    raw_pubs = obj.get("publications", obj if isinstance(obj, list) else [])
    if not isinstance(raw_pubs, list):
        raise ValueError("'publications' must be a list")

    pubs: list[Publication] = []
    for item in raw_pubs:
        if not isinstance(item, dict):
            raise ValueError(f"publication entry is not an object: {item!r}")
        data = dict(item)
        if not data.get("id"):
            raw_authors = data.get("authors")
            if isinstance(raw_authors, str):  # LLM sometimes emits "A, B, C"
                author_list = [s.strip() for s in re.split(r"\s*(?:;| and |,)\s*", raw_authors) if s.strip()]
            else:
                author_list = [a for a in (raw_authors or []) if isinstance(a, str)]
            try:
                year_int = int(data["year"])
            except (KeyError, TypeError, ValueError):
                year_int = None
            if year_int is not None and author_list:
                data["id"] = slug_for(author_list, year_int, str(data.get("title", "")))
            # else: leave id unset -> model_validate raises a clean ValidationError
            # (missing id/year/authors), which triggers the repair round-trip.
        pubs.append(Publication.model_validate(data))

    return PublicationSet(
        publications=pubs, source_fingerprints=fingerprints or {}
    ).deduped()


def extract_publications(
    page_text: str,
    *,
    llm: SupportsComplete,
    system_prompt: str | None = None,
    examples: str = "",
    fingerprints: dict[str, str] | None = None,
    max_page_chars: int = DEFAULT_MAX_PAGE_CHARS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> PublicationSet:
    """Run extraction end to end with one repair retry on bad output."""

    system = system_prompt if system_prompt is not None else _DEFAULT_SYSTEM
    user = build_user_prompt(page_text, examples=examples, max_page_chars=max_page_chars)

    raw = llm.complete(system=system, user=user, max_tokens=max_output_tokens, label="extract")
    try:
        return parse_publication_set(raw, fingerprints=fingerprints)
    except Exception as first_err:  # noqa: BLE001 — repair on any parse/validation issue
        # Compact repair: the model already saw the page; resending it just
        # doubles input tokens. Feed back only its bad output + the error.
        repair_user = (
            "Your previous answer could not be used. It was:\n"
            f"{raw.strip()}\n\nError:\n{first_err}\n\n"
            "Return corrected JSON only, matching the required schema "
            "(the same page as before — do not ask for it again)."
        )
        raw2 = llm.complete(
            system=system, user=repair_user, max_tokens=max_output_tokens, label="extract-repair"
        )
        try:
            return parse_publication_set(raw2, fingerprints=fingerprints)
        except Exception as second_err:  # noqa: BLE001
            raise ExtractionError(
                f"LLM output invalid after repair: {second_err}"
            ) from second_err
