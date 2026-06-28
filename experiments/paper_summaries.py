"""Paper-summary showcase on the live model: 3 sample papers x styles A-E x rag.

Reads sample papers from Supabase, discovers + validates each paper's canonical
link (OpenAlex/Crossref, never Scholar), fetches grounding text (abstract + the
open-access body via ujin when reachable), then for every (style, mode) cell asks
the model for a brief overview. RAG mode feeds only the facet-relevant chunks;
full mode feeds the whole source, so the report shows the rag-vs-full delta and
the samples page can show the writing options side by side.

    python experiments/paper_summaries.py [--n 3] [--model M] [--slugs a,b,c]
                                          [--modes rag,full] [--styles A,B,..]
                                          [--no-fetch] [--no-upsert] [--refresh]

Picks papers whose OpenAlex record is open access (so RAG has real full text to
chunk) and caches the choice to experiments/sample_papers.yaml. Needs
OPENROUTER_API_KEY + SB_* in env/.env, and the extras:
    pip install -e 'backend[rag,experiments]'
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from src.config import Config  # noqa: E402
from src.llm import OpenRouterClient  # noqa: E402
from src.metrics import UsageTracker, cost_breakdown  # noqa: E402
from src.models import Publication  # noqa: E402
from src.paper_samples import (  # noqa: E402
    DEFAULT_MODES,
    DEFAULT_STYLES,
    build_paper_samples,
    sample_row,
)
from src.paper_sources import PaperSources  # noqa: E402
from src.supabase_client import SupabaseClient  # noqa: E402
from src.ujin_client import UjinClient  # noqa: E402

_SAMPLE_FILE = _REPO_ROOT / "experiments" / "sample_papers.yaml"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines into os.environ (no overwrite)."""
    import os

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _row_to_pub(row: dict) -> Publication:
    return Publication.model_validate({**row, "id": row.get("slug") or row.get("id")})


def _pick_oa_papers(sb: SupabaseClient, sources: PaperSources, *, n: int, scan: int) -> list[str]:
    """Pick ``n`` open-access papers (recent, with a DOI + abstract) by slug."""

    rows = sb.select(
        "publications",
        columns="slug,title,authors,year,type,venue,link",
        params={"order": "year.desc", "limit": str(scan), "link": "not.is.null"},
    )
    picked: list[str] = []
    for row in rows:
        pub = _row_to_pub(row)
        if not pub.link:
            continue
        # Prefer papers with reachable open-access full text (PMC) so RAG has a
        # long body to compress; otherwise rag and full collapse to the abstract.
        full = sources.fulltext_by_doi(pub.link)
        if full and len(full) > 2000:
            picked.append(pub.id)
            print(f"  picked {pub.id}  (PMC full text {len(full)} chars)")
            if len(picked) >= n:
                break
    return picked


def _resolve_slugs(args, sb: SupabaseClient, sources: PaperSources) -> list[str]:
    if args.slugs:
        return [s.strip() for s in args.slugs.split(",") if s.strip()]
    if _SAMPLE_FILE.exists() and not args.refresh:
        cached = yaml.safe_load(_SAMPLE_FILE.read_text(encoding="utf-8")) or {}
        slugs = cached.get("slugs") or []
        if slugs:
            print(f"Using cached sample papers from {_SAMPLE_FILE.name}: {slugs}")
            return slugs
    print(f"Auto-picking {args.n} open-access papers (scanning {args.scan} recent)...")
    slugs = _pick_oa_papers(sb, sources, n=args.n, scan=args.scan)
    _SAMPLE_FILE.write_text(yaml.safe_dump({"slugs": slugs}), encoding="utf-8")
    print(f"Cached choice to {_SAMPLE_FILE}")
    return slugs


def _fetch_publications(sb: SupabaseClient, slugs: list[str]) -> list[Publication]:
    pubs: list[Publication] = []
    for slug in slugs:
        rows = sb.select("publications", params={"slug": f"eq.{slug}"})
        if rows:
            pubs.append(_row_to_pub(rows[0]))
        else:
            print(f"  WARNING: no publication row for slug {slug}")
    return pubs


def _render_report(bundles, *, model: str, modes: tuple[str, ...]) -> str:
    L = [
        "PAPER SUMMARY BAKE-OFF",
        f"model: {model}   papers: {len(bundles)}   styles x modes per paper: "
        f"{len(bundles[0].samples) if bundles else 0}",
        "=" * 72,
    ]
    all_samples = [s for b in bundles for s in b.samples]

    # Aggregate rag-vs-full deltas (the whole point of the side-by-side test).
    L.append("RAG vs FULL (averages across all cells):")
    for mode in modes:
        ms = [s for s in all_samples if s.mode == mode]
        if not ms:
            continue
        clean = sum(1 for s in ms if s.evaluation.clean) / len(ms)
        L.append(
            f"  {mode:<5}  src_chars {statistics.mean([s.source_chars for s in ms]):7.0f}"
            f"   out_tokens {statistics.mean([s.completion_tokens for s in ms]):6.0f}"
            f"   in_tokens {statistics.mean([s.prompt_tokens for s in ms]):7.0f}"
            f"   clean {clean:5.0%}"
        )
    in_tok = sum(s.prompt_tokens for s in all_samples)
    out_tok = sum(s.completion_tokens for s in all_samples)
    cost = cost_breakdown(model, in_tok, out_tok)
    L.append(f"  total: in {in_tok}  out {out_tok}  est ${cost['total_cost_usd']:.4f}")
    L.append("=" * 72)

    # Per-paper, per-style detail. Flags: M=em-dash E=emoji L=long S=short T=title F=filler N=ungrounded#
    for b in bundles:
        L.append(f"\n[{b.pub.id}]  {b.pub.title}")
        L.append(
            f"  link: {b.link.canonical_url}   conf {b.link.confidence:.2f}"
            f"   oa: {b.link.oa_url or '-'}   full_text: {b.used_full_text}"
            f"   source {len(b.source_text)} chars"
        )
        L.append(f"  reason: {b.link.reason}")
        for style in sorted({s.style for s in b.samples}):
            for s in [x for x in b.samples if x.style == style]:
                ev = s.evaluation
                L.append(
                    f"  {s.style}/{s.mode:<4} <{ev.flags}> {ev.n_words}w/{ev.n_sentences}s "
                    f"out{s.completion_tokens}  {s.summary[:90]}"
                )
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=3, help="number of sample papers")
    ap.add_argument("--scan", type=int, default=40, help="recent DOI papers to scan when auto-picking")
    ap.add_argument("--slugs", default="", help="comma-separated slugs to use instead of auto-pick")
    ap.add_argument("--model", default=None, help="OpenRouter model (default cfg.model)")
    ap.add_argument("--styles", default=",".join(DEFAULT_STYLES))
    ap.add_argument("--modes", default=",".join(DEFAULT_MODES))
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--no-fetch", action="store_true", help="abstract only; skip ujin full-text fetch")
    ap.add_argument("--no-upsert", action="store_true", help="do not write rows to Supabase")
    ap.add_argument("--refresh", action="store_true", help="re-pick sample papers (ignore cache)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    _load_dotenv(_REPO_ROOT / ".env")
    cfg = Config.from_env()
    model = args.model or cfg.model
    styles = tuple(s.strip().upper() for s in args.styles.split(",") if s.strip())
    modes = tuple(m.strip().lower() for m in args.modes.split(",") if m.strip())

    sb = SupabaseClient(cfg.sb_url, cfg.sb_secret_key)
    sources = PaperSources(contact_email=cfg.contact_email)

    slugs = _resolve_slugs(args, sb, sources)
    if not slugs:
        print("No sample papers found (no open-access DOI papers in the scan window).")
        return 1
    pubs = _fetch_publications(sb, slugs)
    if not pubs:
        print("Could not load any publication rows for the chosen slugs.")
        return 1

    # Full-text fetch (best-effort), unless --no-fetch. ArticleFetcher reads
    # publisher PDFs (pypdf) as well as HTML article bodies (ujin).
    ujin = None
    fetcher = None
    fetch = None
    if not args.no_fetch:
        from src.fetch_text import ArticleFetcher

        ujin = UjinClient(cfg.ujin_url)
        fetcher = ArticleFetcher(ujin=ujin)
        fetch = fetcher.fetch

    embedder = None
    if "rag" in modes:
        from src.rag import MiniLMEmbedder

        print("Loading local embedding model (all-MiniLM-L6-v2)...")
        embedder = MiniLMEmbedder()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else _REPO_ROOT / "experiments" / "runs" / f"papers-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(pubs)} papers x {len(styles)} styles x {len(modes)} modes on {model} ...")
    try:
        with OpenRouterClient(
            cfg.openrouter_api_key, model=model, base_url=cfg.openrouter_base_url,
            tracker=UsageTracker(),
        ) as llm:
            bundles = build_paper_samples(
                pubs,
                sources=sources,
                llm=llm,
                fetch=fetch,
                fulltext_by_doi=sources.fulltext_by_doi,
                embedder=embedder,
                styles=styles,
                modes=modes,
                model=model,
                max_tokens=args.max_tokens,
                on_progress=lambda m: print(" ", m),
            )
    finally:
        if fetcher is not None:
            fetcher.close()
        if ujin is not None:
            ujin.close()
        sources.close()

    report = _render_report(bundles, model=model, modes=modes)
    (out_dir / "report.txt").write_text(report, encoding="utf-8")
    rows = [sample_row(s) for b in bundles for s in b.samples]
    items = [
        {**sample_row(s), "evaluation": asdict(s.evaluation), "title": s.title}
        for b in bundles
        for s in b.samples
    ]
    (out_dir / "items.jsonl").write_text(
        "\n".join(json.dumps(it) for it in items) + "\n", encoding="utf-8"
    )
    print("\n" + report)
    print(f"Wrote report + items to {out_dir}")

    if not args.no_upsert:
        n = sb.upsert("paper_samples", rows, on_conflict="paper_slug,style,mode,model")
        print(f"Upserted {n} rows to Supabase paper_samples.")
    else:
        print("Skipped Supabase upsert (--no-upsert).")
    sb.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
