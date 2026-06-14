"""One-shot orchestration: fetch -> change-detect -> parse/extract -> merge -> publish.

For each configured source we fetch and compare the fingerprint to the stored
one. Changed sources are (re)parsed/extracted; unchanged sources reuse the
publications cached in their state file. We then merge all sources' papers
(deduped by id) into a single :class:`PublicationSet` and upsert it to Supabase
(plus a rebuilt timeline) — but only if something actually changed (so an idle
run does nothing).

Sources are either local CV files (``path:`` — the documents the lab actually
keeps updated, dropped under ``data/inbox``/``data/inputs``, see :mod:`src.cv`)
or scraped URLs (``url:`` — Google Scholar profiles and ordinary pages). The
**CV is primary**: on a duplicate paper (same deterministic slug) the CV's
metadata wins, because CV sources merge first and dedupe keeps the first
occurrence. Scholar is an optional secondary source, **disabled by default**
(``Config.scholar_enabled`` / per-source ``enabled:`` in sources.yaml) —
scraping it tends to trip CAPTCHAs.

All external dependencies (LLM, ujin, state, Supabase) are injected, so the whole
pipeline runs under tests with fakes and no network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src import cv as cv_mod
from src import scholar
from src import timeline as timeline_mod
from src.config import Config
from src.extract import extract_publications, load_system_prompt
from src.models import Publication, PublicationSet, publication_row
from src.obscura_client import ObscuraError
from src.state import StateStore


@dataclass
class Source:
    key: str
    url: str | None = None  # scraped source (Scholar profile or ordinary page)
    path: str | None = None  # local CV file, relative to the data dir
    member: str | None = None
    mode: str | None = None  # overrides Config.scrape_mode when set
    enabled: bool = True


@dataclass
class RunResult:
    changed: bool
    sources_processed: list[str] = field(default_factory=list)
    sources_changed: list[str] = field(default_factory=list)
    total_publications: int = 0
    timeline_entries: int = 0
    parse_summary: dict = field(default_factory=dict)  # CV parse observability


def load_sources(path: str | Path, *, scholar_enabled: bool = False) -> list[Source]:
    """Read the source list from ``sources.yaml``.

    A source's ``enabled:`` flag wins when set; otherwise Scholar-profile URLs
    default to ``scholar_enabled`` (off — Scholar is opt-in) and everything
    else defaults to on.
    """

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = data.get("sources", [])
    sources = []
    for it in items:
        if not it.get("key") or not (it.get("url") or it.get("path")):
            raise ValueError(f"source needs 'key' and one of 'url'/'path': {it!r}")
        enabled = it.get("enabled")
        if enabled is None:
            url = it.get("url")
            enabled = scholar_enabled if url and scholar.is_scholar_profile(url) else True
        sources.append(
            Source(
                key=it["key"], url=it.get("url"), path=it.get("path"),
                member=it.get("member"), mode=it.get("mode"), enabled=bool(enabled),
            )
        )
    if not sources:
        raise ValueError("no sources defined")
    return sources


def load_examples(examples_dir: str | Path | None) -> str:
    """Concatenate any *.txt few-shot example files (empty if none)."""

    if not examples_dir:
        return ""
    d = Path(examples_dir)
    if not d.is_dir():
        return ""
    return "\n\n".join(
        f.read_text(encoding="utf-8") for f in sorted(d.glob("*.txt"))
    ).strip()


def load_style_profile(state_dir: str | Path | None) -> str:
    """Read the saved style profile if present (produced by analyze-style)."""

    if not state_dir:
        return ""
    p = Path(state_dir) / "style_profile.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _fetch_source(
    src: Source, config: Config, *, ujin: Any, obscura: Any
) -> tuple[str, str] | None:
    """Return ``(text, fingerprint)`` for a source, or ``None`` to skip it.

    CV sources (``path:``) are read straight off disk; the fingerprint is the
    file's content hash, so re-running against an untouched CV is a no-op and
    a missing file skips the source (cached publications are reused).

    Google Scholar profiles are rendered to text via obscura (ujin's extractors
    drop the table's authors/venue/year). If obscura is missing or the render
    fails, the Scholar source is **skipped** (returns ``None``) — never silently
    re-extracted from a partial page, which would make the LLM invent metadata.
    Everything else goes through ujin as before.
    """

    if src.path:
        p = Path(src.path)
        if not p.is_absolute():
            # A same-named file dropped into the inbox (the mounted drop
            # folder) overrides the configured location — drop in an updated
            # CV, re-run, done.
            inbox = config.inbox_dir / p.name
            p = inbox if inbox.exists() else Path(config.data_dir) / p
        if not p.exists():
            print(f"  [skip] {src.key}: CV file not found ({p})")
            return None
        raw = p.read_bytes()
        return cv_mod.read_cv_text(p), hashlib.sha256(raw).hexdigest()

    if scholar.is_scholar_profile(src.url):
        if obscura is None or not obscura.available():
            print(f"  [skip] {src.key}: obscura renderer unavailable for Scholar profile")
            return None
        url = scholar.normalize_profile_url(src.url)
        try:
            text = obscura.render_text(url)
        except ObscuraError as exc:
            print(f"  [skip] {src.key}: obscura render failed ({exc})")
            return None
        # Fingerprint the rendered text so an unchanged profile is a no-op.
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()

    res = ujin.scrape(src.url, mode=src.mode or config.scrape_mode)
    return res.text, res.fingerprint


def run(
    config: Config,
    *,
    llm: Any,
    ujin: Any,
    supabase: Any,
    obscura: Any = None,
    state: StateStore | None = None,
    force: bool = False,
    parse_tracker: Any = None,
) -> RunResult:
    """Execute the full pipeline once and (maybe) upsert publications + timeline.

    ``obscura`` (an :class:`~src.obscura_client.ObscuraRenderer`) renders Google
    Scholar profiles to text; when ``None`` or unavailable, Scholar sources are
    skipped (their cached publications are reused) rather than mis-extracted.
    Disabled sources (Scholar, unless opted in) are skipped the same way —
    nothing touches scholar.google.* on a default run.

    ``parse_tracker`` (a :class:`~src.metrics.ParseTracker`) collects per-entry
    CV parse outcomes for the run report.
    """

    state = state or StateStore(config.state_dir)
    sources = load_sources(config.sources_file, scholar_enabled=config.scholar_enabled)
    system_prompt = load_system_prompt(config.templates_dir)
    examples = load_examples(config.examples_dir)
    # Note: descriptions (and the style profile that informs them) are written by
    # the separate opt-in ``describe`` step, not here — keeping extraction cheap.

    fingerprints: dict[str, str] = {}
    per_source: dict[str, list[dict]] = {}
    changed_keys: list[str] = []

    for src in sources:
        if not src.enabled:
            print(f"  [skip] {src.key}: source disabled (Scholar is opt-in)")
            cached = state.get(src.key) or {}
            per_source[src.key] = cached.get("publications", [])
            if cached.get("fingerprint"):
                fingerprints[src.key] = cached["fingerprint"]
            continue
        fetched = _fetch_source(src, config, ujin=ujin, obscura=obscura)
        if fetched is None:
            # Source unreachable this run — reuse whatever we last extracted.
            cached = state.get(src.key) or {}
            per_source[src.key] = cached.get("publications", [])
            if cached.get("fingerprint"):
                fingerprints[src.key] = cached["fingerprint"]
            continue
        text, fingerprint = fetched
        fingerprints[src.key] = fingerprint

        if force or state.changed(src.key, fingerprint):
            if src.path:
                # A CV is a whole document: trim to its publications section,
                # parse entries deterministically, LLM only per failed entry
                # (see src/cv.py + src/cv_parse.py).
                ps = cv_mod.extract_cv_publications(
                    text,
                    llm=llm,
                    system_prompt=system_prompt,
                    examples=examples,
                    parse_tracker=parse_tracker,
                )
            else:
                ps = extract_publications(
                    text,
                    llm=llm,
                    system_prompt=system_prompt,
                    examples=examples,
                )
            pubs = [p.model_dump(mode="json") for p in ps.publications]
            per_source[src.key] = pubs
            changed_keys.append(src.key)
            state.update(
                src.key,
                fingerprint,
                member=src.member,
                pub_count=len(pubs),
                publications=pubs,
            )
        else:
            cached = state.get(src.key) or {}
            per_source[src.key] = cached.get("publications", [])

    parse_summary = parse_tracker.summary if parse_tracker is not None else {}

    if not changed_keys and not force:
        # Nothing changed — leave Supabase untouched; the run was a no-op.
        return RunResult(
            changed=False,
            sources_processed=[s.key for s in sources],
            sources_changed=[],
            parse_summary=parse_summary,
        )

    # Merge CV sources before scraped (Scholar) sources: the CV is the primary
    # source of truth, and dedupe keeps the *first* occurrence of a slug, so on
    # a shared paper the CV metadata wins. Stable sort preserves yaml order
    # within each group.
    merge_order = sorted(sources, key=lambda s: s.path is None)
    merged = [
        Publication.model_validate(d)
        for src in merge_order
        for d in per_source.get(src.key, [])
    ]
    result_set = PublicationSet(
        publications=merged, source_fingerprints=fingerprints
    ).deduped()

    # Publish: upsert every paper (keyed by slug), then fully replace the
    # timeline — the full publication history, newest first (no LLM here —
    # blurbs reuse any saved description).
    supabase.upsert(
        "publications",
        [publication_row(p) for p in result_set.publications],
        on_conflict="slug",
    )
    entries = timeline_mod.build_timeline(result_set, n=None)
    supabase.replace("timeline", [e.row() for e in entries], key="position")

    return RunResult(
        changed=True,
        sources_processed=[s.key for s in sources],
        sources_changed=changed_keys,
        total_publications=len(result_set.publications),
        timeline_entries=len(entries),
        parse_summary=parse_summary,
    )
