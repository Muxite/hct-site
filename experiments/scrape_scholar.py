"""Full Scholar harvest via obscura + cstart pagination -> Supabase.

For each configured profile: walk the ``cstart`` pages (the "Show more" button is
just UI for that GET param), render each ~20-row slice with obscura, extract it
with the LLM (one bounded chunk per call -> good accuracy), dedupe by slug across
pages, and upsert. After all sources, rebuild the site-wide "Latest" timeline
once from the union.

    python experiments/scrape_scholar.py [--dry-run] [--pagesize 20] [--max-pages 20]
                                         [--source fels] [--obscura-bin PATH]

``--dry-run`` extracts everything but writes to a recording fake instead of
Supabase (prints what *would* be written). Needs OPENROUTER_API_KEY + (live) SB_*.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from src import scholar  # noqa: E402
from src import timeline as timeline_mod  # noqa: E402
from src.config import Config  # noqa: E402
from src.extract import extract_publications, load_system_prompt  # noqa: E402
from src.llm import OpenRouterClient  # noqa: E402
from src.metrics import UsageTracker  # noqa: E402
from src.models import Publication, PublicationSet, publication_row  # noqa: E402
from src.obscura_client import BlockedError, ObscuraError, ObscuraRenderer  # noqa: E402
from src.orchestrate import load_sources  # noqa: E402


def _load_dotenv(path: Path) -> None:
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


class _DryRunSupabase:
    """Records writes instead of hitting Supabase."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def upsert(self, table, rows, *, on_conflict=None):
        by = {r["slug"]: r for r in self.tables.get(table, [])}
        for r in rows:
            by[r["slug"]] = r
        self.tables[table] = list(by.values())
        return len(rows)

    def replace(self, table, rows, *, key):
        self.tables[table] = list(rows)
        return len(rows)

    def close(self):
        pass


def harvest_source(
    src, *, obscura, llm, system_prompt, supabase, pagesize, max_pages, delay,
    save_path: Path | None = None,
) -> dict[str, Publication]:
    """Page through one profile, upsert each page, return its slug->pub map.

    ``save_path``: append each page's extracted pubs as JSONL — insurance so a
    mid-run block never loses completed work (replay with ``--from-jsonl``).
    """

    found: dict[str, Publication] = {}
    for page in range(max_pages):
        cstart = page * pagesize
        url = scholar.page_url(src.url, cstart, pagesize=pagesize)
        try:
            text = obscura.render_text(url)
        except BlockedError:
            raise  # global rate-limit: abort the whole run, don't touch the timeline
        except ObscuraError as exc:
            print(f"  [{src.key}] cstart={cstart}: render failed ({exc}); stopping")
            break
        ps = extract_publications(text, llm=llm, system_prompt=system_prompt, max_page_chars=24000)
        new = [p for p in ps.publications if p.id not in found]
        for p in ps.publications:
            found[p.id] = p
        if save_path and ps.publications:
            import json
            with save_path.open("a", encoding="utf-8") as fh:
                for p in ps.publications:
                    fh.write(json.dumps(p.model_dump(mode="json")) + "\n")
        if ps.publications:
            supabase.upsert("publications", [publication_row(p) for p in ps.publications],
                            on_conflict="slug")
        print(f"  [{src.key}] cstart={cstart:3d}: extracted={len(ps.publications):2d} "
              f"new={len(new):2d} running_total={len(found)}")
        # Stop only when a page yields NO new papers (empty, or Scholar clamped &
        # repeated the last slice). Don't stop on a short page: pages legitimately
        # come back with 19 (a merged citation) mid-list, and the LLM can drop one.
        if not new:
            break
        time.sleep(delay)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pagesize", type=int, default=20)
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--source", help="only this source key (e.g. fels)")
    ap.add_argument("--obscura-bin", default=None)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--from-jsonl", help="skip scraping: load pubs from this JSONL and write them")
    args = ap.parse_args(argv)

    _load_dotenv(_REPO_ROOT / ".env")
    cfg = Config.from_env()
    sources = load_sources(cfg.sources_file)
    if args.source:
        sources = [s for s in sources if s.key == args.source]
        if not sources:
            print(f"no source with key {args.source!r}")
            return 1

    if args.from_jsonl:
        # Replay a previous harvest into Supabase — no scraping, no LLM.
        import json
        if args.dry_run:
            supabase = _DryRunSupabase()
        else:
            from src.supabase_client import SupabaseClient
            supabase = SupabaseClient(cfg.sb_url, cfg.sb_secret_key)
        pubs: dict[str, Publication] = {}
        for line in Path(args.from_jsonl).read_text(encoding="utf-8").splitlines():
            if line.strip():
                p = Publication.model_validate(json.loads(line))
                pubs[p.id] = p
        supabase.upsert("publications",
                        [publication_row(p) for p in pubs.values()], on_conflict="slug")
        entries = timeline_mod.build_timeline(PublicationSet(publications=list(pubs.values())))
        supabase.replace("timeline", [e.row() for e in entries], key="position")
        if not args.dry_run:
            supabase.close()
        print(f"Replayed {len(pubs)} publications + {len(entries)} timeline entries "
              f"from {args.from_jsonl}{' (dry-run)' if args.dry_run else ''}")
        return 0

    obscura = ObscuraRenderer(args.obscura_bin or cfg.obscura_bin,
                              wait=cfg.obscura_wait, timeout=cfg.obscura_timeout, min_chars=300)
    if not obscura.available():
        print(f"obscura not available at {obscura.bin!r}")
        return 1
    system_prompt = load_system_prompt(cfg.templates_dir)
    tracker = UsageTracker(label="scrape-scholar")

    if args.dry_run:
        supabase = _DryRunSupabase()
    else:
        from src.supabase_client import SupabaseClient
        supabase = SupabaseClient(cfg.sb_url, cfg.sb_secret_key)

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    save_path = _REPO_ROOT / "experiments" / "runs" / f"scholar-harvest-{ts}.jsonl"
    save_path.parent.mkdir(parents=True, exist_ok=True)

    all_pubs: dict[str, Publication] = {}
    with OpenRouterClient(cfg.openrouter_api_key, model=cfg.model,
                          base_url=cfg.openrouter_base_url, tracker=tracker) as llm:
        print(f"{'DRY-RUN' if args.dry_run else 'LIVE'} harvest of {len(sources)} source(s) "
              f"@ pagesize={args.pagesize} on {cfg.model}  (saving to {save_path.name})")
        blocked = False
        for src in sources:
            try:
                found = harvest_source(
                    src, obscura=obscura, llm=llm, system_prompt=system_prompt,
                    supabase=supabase, pagesize=args.pagesize, max_pages=args.max_pages,
                    delay=args.delay, save_path=save_path,
                )
            except BlockedError as exc:
                print(f"  [{src.key}] BLOCKED: {exc}")
                print("  Google rate-limited us; stop all requests and retry after a cooldown.")
                blocked = True
                break
            all_pubs.update(found)
            print(f"  [{src.key}] DONE: {len(found)} publications")

        # Only rebuild the timeline from a real harvest — never wipe it with an
        # empty/partial set (a blocked or empty run leaves existing rows intact).
        entries = []
        if all_pubs and not blocked:
            entries = timeline_mod.build_timeline(PublicationSet(publications=list(all_pubs.values())))
            supabase.replace("timeline", [e.row() for e in entries], key="position")
        elif blocked:
            print("  [timeline] left unchanged (run was blocked).")

    if not args.dry_run:
        supabase.close()
    t = tracker.totals
    print(f"\nTOTAL: {len(all_pubs)} unique publications, {len(entries)} timeline entries")
    print(f"LLM: {t['calls']} calls, {t['total_tokens']} tokens, {t['latency_s']}s, "
          f"~${t['cost_usd']:.4f}")
    if args.dry_run:
        print("\n[dry-run] newest 8 that WOULD be written:")
        newest = sorted(all_pubs.values(), key=lambda p: p.year, reverse=True)[:8]
        for p in newest:
            print(f"  {p.year} {p.type.value:11s} {p.title[:60]!r} — {p.authors[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
