"""Command-line entry point for hct-manager.

    hct-manager run [--force]          scrape -> extract -> upsert publications + timeline
    hct-manager import-html [--max-chars N] [--no-timeline] [--no-blurbs]
                                       extract publications from the static page (no Scholar)
    hct-manager migrate-content [--no-ai]   parse static HTML -> people/research/site_content
    hct-manager analyze-style FILE [--save]   write/print a style profile
    hct-manager describe [--all] [--fetch] [--limit N]   write lab-voice descriptions
    hct-manager qa [--out PATH] [--no-source-check] [--strict]
                                       QA report on the live Supabase data
    hct-manager health                 check the ujin scrape service

Designed to be run on demand (and exit) — no daemon, no scheduler. All site data
is written to Supabase (the frontend reads it directly with the publishable key).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import Config
from src.llm import OpenRouterClient
from src.style import analyze_style, load_style_system_prompt, read_text_input
from src.supabase_client import SupabaseClient
from src.ujin_client import UjinClient


def _make_llm(cfg: Config, tracker=None) -> OpenRouterClient:
    return OpenRouterClient(
        cfg.openrouter_api_key, model=cfg.model, base_url=cfg.openrouter_base_url,
        tracker=tracker,
    )


def _finalize_metrics(cfg: Config, tracker) -> None:
    """Persist a run's LLM token/latency usage and print a one-line summary."""
    if tracker is None or not tracker.records:
        return
    tracker.dump_jsonl(cfg.state_dir / "metrics.jsonl")
    t = tracker.totals
    print(
        f"LLM usage: {t['calls']} calls, {t['total_tokens']} tokens "
        f"({t['prompt_tokens']} in / {t['completion_tokens']} out), "
        f"{t['latency_s']}s, ~${t['cost_usd']:.4f}."
    )


def _make_supabase(cfg: Config) -> SupabaseClient:
    return SupabaseClient(cfg.sb_url, cfg.sb_secret_key)


def _row_to_publication(row: dict):
    from src.models import Publication

    return Publication.model_validate({**row, "id": row.get("slug") or row.get("id")})


def _cmd_run(args: argparse.Namespace) -> int:
    from src import orchestrate

    from src.metrics import UsageTracker

    cfg = Config.from_env()
    tracker = UsageTracker(label="run")
    with UjinClient(cfg.ujin_url) as ujin, _make_llm(cfg, tracker) as llm, _make_supabase(cfg) as sb:
        result = orchestrate.run(cfg, llm=llm, ujin=ujin, supabase=sb, force=args.force)
    _finalize_metrics(cfg, tracker)

    if not result.changed:
        print(f"No changes across {len(result.sources_processed)} source(s); nothing written.")
        return 0
    print(
        f"Published {result.total_publications} publications + {result.timeline_entries} "
        f"timeline entries (changed sources: {', '.join(result.sources_changed)})."
    )
    return 0


def _cmd_import_html(args: argparse.Namespace) -> int:
    """Populate publications + timeline from the static page (no ujin/Scholar).

    Useful when Google Scholar blocks the runner: the page's own
    ``#publications-static`` list is fed through the normal extract -> validate ->
    timeline pipeline. Input is capped (``--max-chars``, newest first) so the JSON
    output doesn't exceed the model's token budget.
    """
    from src import content
    from src import timeline as timeline_mod
    from src.describe import load_describe_system_prompt
    from src.extract import extract_publications, load_system_prompt
    from src.models import publication_row

    from src.metrics import UsageTracker

    cfg = Config.from_env()
    text = content.publications_block_text(cfg.index_html.read_text(encoding="utf-8"))
    if not text:
        print(f"No #publications-static block found in {cfg.index_html}.")
        return 1

    tracker = UsageTracker(label="import-html")
    with _make_llm(cfg, tracker) as llm, _make_supabase(cfg) as sb:
        ps = extract_publications(
            text,
            llm=llm,
            system_prompt=load_system_prompt(cfg.templates_dir),
            max_page_chars=args.max_chars,
        )
        n = sb.upsert(
            "publications",
            [publication_row(p) for p in ps.publications],
            on_conflict="slug",
        )
        msg = f"Imported {n} publications from {cfg.index_html.name}"
        if not args.no_timeline:
            entries = timeline_mod.build_timeline(
                ps,
                llm=None if args.no_blurbs else llm,
                describe_system=load_describe_system_prompt(cfg.templates_dir),
            )
            sb.replace("timeline", [e.row() for e in entries], key="position")
            msg += f" + {len(entries)} timeline entries"
    _finalize_metrics(cfg, tracker)
    print(msg + ".")
    return 0


def _cmd_migrate_content(args: argparse.Namespace) -> int:
    from src import content
    from src.orchestrate import load_style_profile

    cfg = Config.from_env()
    html = cfg.index_html.read_text(encoding="utf-8")
    style_profile = load_style_profile(cfg.state_dir)

    llm = None
    try:
        if not args.no_ai:
            llm = _make_llm(cfg)
        people, research, site_content = content.build_content(
            html, llm=llm, style_profile=style_profile
        )
    finally:
        if llm is not None:
            llm.close()

    with _make_supabase(cfg) as sb:
        sb.replace("people", [p.row() for p in people], key="name")
        sb.replace("research", [r.row() for r in research], key="title")
        sb.upsert("site_content", [c.row() for c in site_content], on_conflict="key")

    print(
        f"Migrated content: {len(people)} people, {len(research)} research, "
        f"{len(site_content)} site_content keys."
    )
    return 0


def _cmd_analyze_style(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    text = read_text_input(args.path)
    system = load_style_system_prompt(cfg.templates_dir)
    with _make_llm(cfg) as llm:
        profile = analyze_style(text, llm=llm, system_prompt=system)

    if args.save:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.state_dir / "style_profile.txt"
        out.write_text(profile + "\n", encoding="utf-8")
        print(f"Saved style profile to {out}")
    else:
        print(profile)
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    from src import describe
    from src.metrics import UsageTracker
    from src.models import PublicationSet, publication_row
    from src.orchestrate import load_style_profile

    cfg = Config.from_env()
    tracker = UsageTracker(label="describe")
    style_profile = load_style_profile(cfg.state_dir)
    system = describe.load_describe_system_prompt(cfg.templates_dir)

    fetch = None
    ujin = None
    if args.fetch:
        ujin = UjinClient(cfg.ujin_url)
        fetch = lambda link: ujin.scrape(link, mode="article").text  # noqa: E731

    with _make_supabase(cfg) as sb:
        rows = sb.select("publications")
        ps = PublicationSet(publications=[_row_to_publication(r) for r in rows])
        try:
            with _make_llm(cfg, tracker) as llm:
                written = describe.describe_set(
                    ps,
                    llm=llm,
                    system_prompt=system,
                    style_profile=style_profile,
                    fetch=fetch,
                    only_missing=not args.all,
                    limit=args.limit,
                )
        finally:
            if ujin is not None:
                ujin.close()

        _finalize_metrics(cfg, tracker)
        if written == 0:
            print("No descriptions written (nothing to do).")
            return 0
        sb.upsert(
            "publications",
            [publication_row(p) for p in ps.publications if p.description],
            on_conflict="slug",
        )
    print(f"Wrote {written} description(s) to Supabase.")
    return 0


def _cmd_qa(args: argparse.Namespace) -> int:
    """Pull the live Supabase data and write a plain-text QA report.

    Reads every table, runs the schema / completeness / AI-writing / source
    checks (:mod:`src.qa`), prints the report, and writes it to
    ``--out`` (default ``state/qa-report.txt``). Exit code is non-zero when any
    ERROR finding exists (or any WARN under ``--strict``) so this can gate a
    publish or CI run.
    """
    from src import qa

    cfg = Config.from_env()
    tables = ["publications", "timeline", "people", "research", "site_content"]
    with _make_supabase(cfg) as sb:
        rows = {t: sb.select(t) for t in tables}

    source = None
    if not args.no_source_check and cfg.index_html.exists():
        source = qa.build_source(cfg.index_html.read_text(encoding="utf-8"))

    report = qa.run_qa(rows, source=source, strict=args.strict, source_url=cfg.sb_url)
    text = report.render()
    print(text, end="")

    out = Path(args.out) if args.out else cfg.state_dir / "qa-report.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"\nWrote report to {out}")
    return report.exit_code


def _cmd_health(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    with UjinClient(cfg.ujin_url) as ujin:
        ok = ujin.health()
    print(f"ujin scrape service @ {cfg.ujin_url}: {'OK' if ok else 'UNREACHABLE'}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hct-manager", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="scrape + extract + upsert publications + timeline")
    p_run.add_argument(
        "--force", action="store_true", help="ignore fingerprints; re-extract every source"
    )
    p_run.set_defaults(func=_cmd_run)

    p_imp = sub.add_parser(
        "import-html", help="extract publications from the static page (no Scholar) and upsert"
    )
    p_imp.add_argument(
        "--max-chars", type=int, default=6000,
        help="cap on page text sent to the LLM, newest first (avoids JSON output truncation)",
    )
    p_imp.add_argument("--no-timeline", action="store_true", help="don't rebuild the timeline")
    p_imp.add_argument(
        "--no-blurbs", action="store_true", help="build the timeline without AI blurbs (cheaper)"
    )
    p_imp.set_defaults(func=_cmd_import_html)

    p_mig = sub.add_parser("migrate-content", help="parse static HTML into people/research/site_content")
    p_mig.add_argument(
        "--no-ai", action="store_true", help="skip AI enrichment (don't write research descriptions)"
    )
    p_mig.set_defaults(func=_cmd_migrate_content)

    p_style = sub.add_parser("analyze-style", help="analyze a document's writing style")
    p_style.add_argument("path", help="path to a .docx/.txt/.md/.tex document")
    p_style.add_argument(
        "--save", action="store_true", help="save profile to state/style_profile.txt"
    )
    p_style.set_defaults(func=_cmd_analyze_style)

    p_desc = sub.add_parser("describe", help="write lab-voice descriptions into Supabase")
    p_desc.add_argument(
        "--all", action="store_true", help="re-describe every paper (default: only missing)"
    )
    p_desc.add_argument(
        "--fetch", action="store_true", help="scrape each paper's link via ujin for grounding"
    )
    p_desc.add_argument(
        "--limit", type=int, default=None, help="write at most N descriptions this run"
    )
    p_desc.set_defaults(func=_cmd_describe)

    p_qa = sub.add_parser("qa", help="QA report on the live Supabase data")
    p_qa.add_argument(
        "--out", default=None, help="report path (default: state/qa-report.txt)"
    )
    p_qa.add_argument(
        "--no-source-check", action="store_true",
        help="skip the cross-check against the static index.html",
    )
    p_qa.add_argument(
        "--strict", action="store_true", help="exit non-zero on warnings too, not just errors"
    )
    p_qa.set_defaults(func=_cmd_qa)

    p_health = sub.add_parser("health", help="check the ujin scrape service")
    p_health.set_defaults(func=_cmd_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
