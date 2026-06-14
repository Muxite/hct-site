"""Turn ujin job *chunk events* into validated publications in Supabase.

The new ujin handles Scholar pagination + chunking for us: a ``browser`` source
clicks "Show more" until the profile is fully loaded, harvests each row
(``extract: raw`` + ``results_selector: .gsc_a_tr`` -> ``[{"text", "href"}]``),
and a ``chunk`` transform fans the rows out 20-at-a-time. Each chunk arrives here
as one event ``{job_id, fingerprint, payload: [rows], chunk_index, chunk_total}``.

This module is the hct half: extract one chunk's rows with the LLM (bounded
context -> good accuracy), validate, and upsert. It deliberately has **no ujin
import** so it is unit-testable with fakes; the ujin plugin in
``backend/ujin_plugins/`` is a thin adapter that calls :class:`ScholarIngestor`.

Timeline: we don't trust chunk ordering, so the ingestor accumulates the run's
publications (reset on ``chunk_index == 0``) and rebuilds the small "Latest"
timeline from everything seen so far on each chunk. Publication upserts are
keyed by slug (additive), so a partial run never deletes existing rows.
"""

from __future__ import annotations

from typing import Any

from src import timeline as timeline_mod
from src.extract import extract_publications
from src.models import Publication, PublicationSet, publication_row


def chunk_text(payload: Any) -> str:
    """Flatten a chunk event payload into page-like text for the extractor.

    ``payload`` is normally a list of ``{"text", "href"}`` rows (browser
    ``extract: raw``); it may also be a raw HTML/text string. Empty -> "".
    """

    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        parts = []
        for it in payload:
            if isinstance(it, dict):
                text = (it.get("text") or "").strip()
            else:
                text = str(it).strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    return ""


class ScholarIngestor:
    """Stateful per-job ingestor: chunk event -> extract -> upsert (+ timeline).

    ``llm`` and ``supabase`` follow the same protocols the rest of the backend
    uses (``llm.complete(...)``; ``supabase.upsert(table, rows, on_conflict=...)``
    / ``supabase.replace(table, rows, key=...)``).
    """

    def __init__(
        self,
        *,
        llm: Any,
        supabase: Any,
        system_prompt: str | None = None,
        examples: str = "",
    ) -> None:
        self._llm = llm
        self._supabase = supabase
        self._system_prompt = system_prompt
        self._examples = examples
        self._seen: dict[str, Publication] = {}

    def handle(self, event: dict) -> dict:
        """Process one chunk event. Returns a small summary dict (for logging)."""

        if int(event.get("chunk_index", 0) or 0) == 0:
            self._seen = {}  # a fresh harvest of this profile starts at chunk 0

        text = chunk_text(event.get("payload"))
        if not text:
            return {"written": 0, "total": len(self._seen), "skipped": "empty-chunk"}

        ps = extract_publications(
            text, llm=self._llm,
            system_prompt=self._system_prompt, examples=self._examples,
        )
        rows = [publication_row(p) for p in ps.publications]
        if rows:
            self._supabase.upsert("publications", rows, on_conflict="slug")
        for p in ps.publications:
            self._seen[p.id] = p

        # Rebuild the small "Latest" timeline from everything seen this run so far
        # (order-independent; build_timeline picks the newest entries itself).
        entries = timeline_mod.build_timeline(
            PublicationSet(publications=list(self._seen.values()))
        )
        self._supabase.replace("timeline", [e.row() for e in entries], key="position")

        return {
            "written": len(rows),
            "total": len(self._seen),
            "timeline": len(entries),
            "chunk_index": event.get("chunk_index"),
            "chunk_total": event.get("chunk_total"),
        }
