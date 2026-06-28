"""Orchestrate the paper-summary bake-off: discover -> fetch -> RAG -> generate.

For each paper we (1) discover and validate a canonical link plus a free
full-text URL, (2) assemble grounding text (the API abstract, enriched with the
fetched open-access body when reachable), then (3) generate one RAG-grounded
summary for each of five styles A-E. Each summary is evaluated and its tokens
isolated, so the page can show the style options side by side.

Everything here takes injected collaborators (a :class:`PaperSources`, an optional
``fetch`` callable, an optional :class:`Embedder`, and an LLM), so it is fully
unit-tested with fakes. The live wiring (real clients, Supabase upsert, report) is
in ``experiments/paper_summaries.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from src.models import Publication
from src.paper_sources import LinkResult, PaperSources, _doi_only
from src.rag import Embedder, build_context
from src.summarize import (
    STYLES,
    SummaryEval,
    evaluate_summary,
    summarize_paper,
)

DEFAULT_STYLES: tuple[str, ...] = ("A", "B", "C", "D", "E")
DEFAULT_MODES: tuple[str, ...] = ("rag",)
# Below this many fetched chars we treat the open-access body as not worth using
# and fall back to the abstract (avoids feeding a cookie-wall / stub page).
_MIN_FULLTEXT_CHARS = 400


class SupportsComplete(Protocol):
    tracker: Any  # optional UsageTracker, read for per-call token isolation

    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


@dataclass
class PaperSample:
    """One (paper, style, mode) cell of the bake-off."""

    paper_slug: str
    title: str
    authors: list[str]
    year: int
    style: str
    mode: str
    model: str
    summary: str
    link: str | None
    oa_url: str | None
    confidence: float
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    position: int
    source_chars: int  # how much grounding text this mode fed the model
    evaluation: SummaryEval


@dataclass
class PaperBundle:
    """Everything produced for one paper: its link discovery + all its samples."""

    pub: Publication
    link: LinkResult
    source_text: str
    used_full_text: bool
    samples: list[PaperSample] = field(default_factory=list)


def fetch_source_text(
    link: LinkResult,
    fetch: Callable[[str], str] | None,
    fulltext_by_doi: Callable[[str], str] | None = None,
) -> tuple[str, bool]:
    """Assemble grounding text for a paper: abstract, enriched with OA full text.

    Tries, in order, an open-access full-text resolver keyed on the DOI
    (``fulltext_by_doi``, e.g. PMC), then fetching the OA URL and the canonical
    URL (the OA link is usually a PDF, the canonical may redirect to HTML), and
    keeps the longest body. Prefers a substantial body (more grounding for RAG to
    chunk); falls back to the abstract. All sources are best-effort - any error
    degrades gracefully. Returns ``(text, used_full_text)``.
    """

    abstract = (link.abstract or "").strip()
    full = ""
    doi = (link.record.doi if link.record else None) or _doi_only(link.canonical_url)
    if fulltext_by_doi and doi:
        try:
            full = (fulltext_by_doi(doi) or "").strip()
        except Exception:  # noqa: BLE001 - grounding is best-effort
            full = ""
    if fetch and len(full) < _MIN_FULLTEXT_CHARS:
        seen: set[str] = set()
        for url in (link.oa_url, link.canonical_url):
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                candidate = (fetch(url) or "").strip()
            except Exception:  # noqa: BLE001 - grounding is best-effort
                candidate = ""
            if len(candidate) > len(full):
                full = candidate
    if len(full) >= _MIN_FULLTEXT_CHARS and len(full) > len(abstract):
        # Keep the abstract on top so its framing is always in scope, then body.
        text = f"{abstract}\n\n{full}".strip() if abstract else full
        return text, True
    return abstract, False


def _tokens(llm: SupportsComplete) -> tuple[int, int, float]:
    tracker = getattr(llm, "tracker", None)
    if tracker is None:
        return 0, 0, 0.0
    t = tracker.totals
    return t.get("prompt_tokens", 0), t.get("completion_tokens", 0), t.get("latency_s", 0.0)


def build_paper_samples(
    papers: list[Publication],
    *,
    sources: PaperSources,
    llm: SupportsComplete,
    fetch: Callable[[str], str] | None = None,
    fulltext_by_doi: Callable[[str], str] | None = None,
    embedder: Embedder | None = None,
    styles: tuple[str, ...] = DEFAULT_STYLES,
    modes: tuple[str, ...] = DEFAULT_MODES,
    model: str = "",
    full_max_chars: int = 6000,
    rag_max_chars: int = 2400,
    max_tokens: int = 400,
    on_progress: Callable[[str], None] | None = None,
) -> list[PaperBundle]:
    """Run the full matrix over ``papers`` and return one bundle per paper.

    ``llm`` may carry a ``tracker`` attribute (a UsageTracker); if so it is reset
    per call so each cell's token cost is isolated, exactly as ``describe_eval``
    does. ``embedder`` is required only if ``"rag"`` is in ``modes``.
    """

    if "rag" in modes and embedder is None:
        raise ValueError("'rag' mode requires an embedder")

    from src.metrics import UsageTracker  # local import; metrics has no heavy deps

    bundles: list[PaperBundle] = []
    position = 0
    for pub in papers:
        if on_progress:
            on_progress(f"discover: {pub.title[:60]}")
        link = sources.discover(
            title=pub.title, authors=pub.authors, year=pub.year, doi=pub.link
        )
        source_text, used_full = fetch_source_text(link, fetch, fulltext_by_doi)

        # Context depends only on the mode, so build each once and reuse per style.
        contexts: dict[str, str] = {}
        for mode in modes:
            contexts[mode] = build_context(
                source_text,
                mode=mode,
                embedder=embedder,
                full_max_chars=full_max_chars,
                rag_max_chars=rag_max_chars,
            )

        bundle = PaperBundle(pub=pub, link=link, source_text=source_text, used_full_text=used_full)
        for style in styles:
            for mode in modes:
                context = contexts[mode]
                if hasattr(llm, "tracker"):
                    llm.tracker = UsageTracker(label="summary")
                try:
                    summary = summarize_paper(
                        pub, llm=llm, style=style, context=context, max_tokens=max_tokens
                    )
                except Exception as exc:  # noqa: BLE001 - a failed cell is a measured outcome
                    summary = ""
                    if on_progress:
                        on_progress(f"  cell {style}/{mode} failed: {exc}")
                p_tok, c_tok, lat = _tokens(llm)
                bundle.samples.append(
                    PaperSample(
                        paper_slug=pub.id,
                        title=pub.title,
                        authors=list(pub.authors),
                        year=pub.year,
                        style=style,
                        mode=mode,
                        model=model,
                        summary=summary,
                        link=link.canonical_url,
                        oa_url=link.oa_url,
                        confidence=round(link.confidence, 3),
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        latency_s=round(lat, 3),
                        position=position,
                        source_chars=len(context),
                        evaluation=evaluate_summary(summary, pub, source_text=source_text),
                    )
                )
                position += 1
        bundles.append(bundle)
        if on_progress:
            on_progress(f"  {len(bundle.samples)} samples; full_text={used_full}; link={link.canonical_url}")
    return bundles


def sample_row(s: PaperSample) -> dict[str, Any]:
    """Map a :class:`PaperSample` to a ``paper_samples`` table row.

    Only the persisted columns; ``id``/``created_at`` are server-generated. The
    evaluation flags stay out of the DB - they live in the harness report.
    """

    return {
        "paper_slug": s.paper_slug,
        "style": s.style,
        "mode": s.mode,
        "model": s.model,
        "summary": s.summary,
        "link": s.link,
        "oa_url": s.oa_url,
        "confidence": s.confidence,
        "prompt_tokens": s.prompt_tokens,
        "completion_tokens": s.completion_tokens,
        "latency_s": s.latency_s,
        "position": s.position,
    }


def all_styles() -> dict[str, str]:
    """The style key -> profile map (re-exported for the harness/report)."""

    return dict(STYLES)
