"""One-shot orchestration: scrape -> change-detect -> extract -> merge -> publish.

For each configured source we scrape via ujin and compare the fingerprint to the
stored one. Changed sources are (re)extracted by the LLM; unchanged sources reuse
the publications cached in their state file. We then merge all sources' papers
(deduped by id) into a single :class:`PublicationSet` and upsert it to Supabase
(plus a rebuilt timeline) — but only if something actually changed (so an idle
run does nothing).

All external dependencies (LLM, ujin, state, Supabase) are injected, so the whole
pipeline runs under tests with fakes and no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src import timeline as timeline_mod
from src.config import Config
from src.extract import extract_publications, load_system_prompt
from src.models import Publication, PublicationSet, publication_row
from src.state import StateStore


@dataclass
class Source:
    key: str
    url: str
    member: str | None = None
    mode: str | None = None  # overrides Config.scrape_mode when set


@dataclass
class RunResult:
    changed: bool
    sources_processed: list[str] = field(default_factory=list)
    sources_changed: list[str] = field(default_factory=list)
    total_publications: int = 0
    timeline_entries: int = 0


def load_sources(path: str | Path) -> list[Source]:
    """Read the source list from ``sources.yaml``."""

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = data.get("sources", [])
    sources = []
    for it in items:
        if not it.get("key") or not it.get("url"):
            raise ValueError(f"source needs 'key' and 'url': {it!r}")
        sources.append(
            Source(key=it["key"], url=it["url"], member=it.get("member"), mode=it.get("mode"))
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


def run(
    config: Config,
    *,
    llm: Any,
    ujin: Any,
    supabase: Any,
    state: StateStore | None = None,
    force: bool = False,
) -> RunResult:
    """Execute the full pipeline once and (maybe) upsert publications + timeline."""

    state = state or StateStore(config.state_dir)
    sources = load_sources(config.sources_file)
    system_prompt = load_system_prompt(config.templates_dir)
    examples = load_examples(config.examples_dir)
    # Note: descriptions (and the style profile that informs them) are written by
    # the separate opt-in ``describe`` step, not here — keeping extraction cheap.

    fingerprints: dict[str, str] = {}
    per_source: dict[str, list[dict]] = {}
    changed_keys: list[str] = []

    for src in sources:
        res = ujin.scrape(src.url, mode=src.mode or config.scrape_mode)
        fingerprints[src.key] = res.fingerprint

        if force or state.changed(src.key, res.fingerprint):
            ps = extract_publications(
                res.text,
                llm=llm,
                system_prompt=system_prompt,
                examples=examples,
            )
            pubs = [p.model_dump(mode="json") for p in ps.publications]
            per_source[src.key] = pubs
            changed_keys.append(src.key)
            state.update(
                src.key,
                res.fingerprint,
                member=src.member,
                pub_count=len(pubs),
                publications=pubs,
            )
        else:
            cached = state.get(src.key) or {}
            per_source[src.key] = cached.get("publications", [])

    if not changed_keys and not force:
        # Nothing changed — leave Supabase untouched; the run was a no-op.
        return RunResult(
            changed=False,
            sources_processed=[s.key for s in sources],
            sources_changed=[],
        )

    merged = [
        Publication.model_validate(d)
        for pubs in per_source.values()
        for d in pubs
    ]
    result_set = PublicationSet(
        publications=merged, source_fingerprints=fingerprints
    ).deduped()

    # Publish: upsert every paper (keyed by slug), then fully replace the small
    # "Latest" timeline (no LLM here — blurbs reuse any saved description).
    supabase.upsert(
        "publications",
        [publication_row(p) for p in result_set.publications],
        on_conflict="slug",
    )
    entries = timeline_mod.build_timeline(result_set)
    supabase.replace("timeline", [e.row() for e in entries], key="position")

    return RunResult(
        changed=True,
        sources_processed=[s.key for s in sources],
        sources_changed=changed_keys,
        total_publications=len(result_set.publications),
        timeline_entries=len(entries),
    )
