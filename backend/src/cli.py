"""Command-line entry point for hct-manager.

    hct-manager run [--force]          CV (+ optional Scholar) -> parse/extract -> upsert
    hct-manager sync-content [--people PATH] [--research PATH] [--site PATH]
                                       people.yaml/research.yaml/site.yaml -> Supabase
    hct-manager analyze-style FILE [--save]   write/print a style profile
    hct-manager describe [--all] [--fetch] [--limit N]   write lab-voice descriptions
    hct-manager qa [--out PATH] [--no-source-check] [--strict]
                                       QA report on the live Supabase data
    hct-manager health                 check the ujin scrape service
    hct-manager viewer [--host H] [--port P] [--debug]
                                       localhost read+edit viewer over the tables

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


def _finalize_parse(cfg: Config, parse_tracker) -> None:
    """Persist per-entry CV parse outcomes + the run summary; print the table."""
    if parse_tracker is None or not parse_tracker.records:
        return
    parse_tracker.dump_jsonl(cfg.state_dir / "parse-report.jsonl")
    parse_tracker.dump_summary(cfg.state_dir / "parse-summary.jsonl")
    print(parse_tracker.render())


def _make_supabase(cfg: Config) -> SupabaseClient:
    return SupabaseClient(cfg.sb_url, cfg.sb_secret_key)


def _content_path(cfg: Config, override: str | None, filename: str) -> Path:
    """Resolve a content YAML: explicit flag > inbox (drop folder) > inputs."""
    if override:
        return Path(override)
    inbox = cfg.inbox_dir / filename
    return inbox if inbox.exists() else cfg.inputs_dir / filename


def _row_to_publication(row: dict):
    from src.models import Publication

    return Publication.model_validate({**row, "id": row.get("slug") or row.get("id")})


def _cmd_run(args: argparse.Namespace) -> int:
    from src import orchestrate
    from src.obscura_client import ObscuraRenderer

    from src.metrics import ParseTracker, UsageTracker

    cfg = Config.from_env()
    tracker = UsageTracker(label="run")
    parse_tracker = ParseTracker(label="run")
    obscura = ObscuraRenderer(
        cfg.obscura_bin, wait=cfg.obscura_wait, timeout=cfg.obscura_timeout
    )
    with UjinClient(cfg.ujin_url) as ujin, _make_llm(cfg, tracker) as llm, _make_supabase(cfg) as sb:
        result = orchestrate.run(
            cfg, llm=llm, ujin=ujin, supabase=sb, obscura=obscura, force=args.force,
            parse_tracker=parse_tracker,
        )
    _finalize_metrics(cfg, tracker)
    _finalize_parse(cfg, parse_tracker)

    if not result.changed:
        print(f"No changes across {len(result.sources_processed)} source(s); nothing written.")
        return 0
    print(
        f"Published {result.total_publications} publications + {result.timeline_entries} "
        f"timeline entries (changed sources: {', '.join(result.sources_changed)})."
    )
    return 0


def _cmd_sync_content(args: argparse.Namespace) -> int:
    """Sync people.yaml + research.yaml + site.yaml into Supabase.

    The YAML files are the source of truth for the roster, project list, and
    site boilerplate (header/nav + the free-text prose sections), including
    current/alumni and current/archived status. They're read from the drop
    folder (``inbox/``) when present, else from the committed defaults in
    ``inputs/``. No LLM involved.
    """
    from src import content
    from src import sync_content as sync_mod

    cfg = Config.from_env()
    people_path = _content_path(cfg, args.people, "people.yaml")
    research_path = _content_path(cfg, args.research, "research.yaml")
    site_path = _content_path(cfg, args.site, "site.yaml")

    site_content = []
    if site_path.exists():
        site_content = content.load_site_yaml(site_path)

    with _make_supabase(cfg) as sb:
        n_people, n_research = sync_mod.sync_content(
            people_path, research_path, supabase=sb
        )
        if site_content:
            sb.upsert("site_content", [c.row() for c in site_content], on_conflict="key")

    print(
        f"Synced content: {n_people} people ({people_path.name}), "
        f"{n_research} research ({research_path.name}), "
        f"{len(site_content)} site_content keys ({site_path.name})."
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

    # Legacy cross-check against a *rendered* static page (the publications-static
    # block). The live site is now a React/Vite app, so this only runs if someone
    # points HCT_INDEX_HTML at a real rendered snapshot — the Vite shell (no
    # publications block) is skipped to avoid spurious "not in static page" warnings.
    source = None
    if not args.no_source_check and cfg.index_html.exists():
        from src import content

        html = cfg.index_html.read_text(encoding="utf-8")
        if content.publications_block_text(html):
            people_names: list[str] = []
            people_path = _content_path(cfg, None, "people.yaml")
            if people_path.exists():
                from src.sync_content import load_people_yaml

                people_names = [p.name for p in load_people_yaml(people_path)]
            source = qa.build_source(html, people_names=people_names)

    report = qa.run_qa(rows, source=source, strict=args.strict, source_url=cfg.sb_url)
    text = report.render()
    print(text, end="")

    out = Path(args.out) if args.out else cfg.state_dir / "qa-report.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"\nWrote report to {out}")
    return report.exit_code


def _cmd_viewer(args: argparse.Namespace) -> int:
    """Serve the localhost admin viewer (read + edit) over the Supabase tables.

    Not the public site — a server-rendered SQL-style view of what the agent
    wrote, one page per table. people/research/site_content edits are written
    back to their YAML files and re-synced; publications/timeline edits upsert
    straight to Supabase. Needs the ``viewer`` extra (FastAPI + uvicorn).
    """
    try:
        import uvicorn

        from src import viewer
    except ModuleNotFoundError:
        print("the viewer needs the [viewer] extra — install it with: pip install -e .[viewer]")
        return 1

    cfg = Config.from_env()
    people_path = _content_path(cfg, None, "people.yaml")
    research_path = _content_path(cfg, None, "research.yaml")
    site_path = _content_path(cfg, None, "site.yaml")

    with _make_supabase(cfg) as sb:
        app = viewer.create_app(
            supabase=sb, people_path=people_path,
            research_path=research_path, site_path=site_path,
        )
        print(f"HCT data viewer on http://{args.host}:{args.port}  (Ctrl+C to stop)")
        uvicorn.run(
            app, host=args.host, port=args.port,
            log_level="debug" if args.debug else "info",
        )
    return 0


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

    p_sync = sub.add_parser(
        "sync-content",
        help="sync people.yaml/research.yaml/site.yaml into Supabase",
    )
    p_sync.add_argument(
        "--people", default=None, help="path to people.yaml (default: inbox/, else inputs/)"
    )
    p_sync.add_argument(
        "--research", default=None, help="path to research.yaml (default: inbox/, else inputs/)"
    )
    p_sync.add_argument(
        "--site", default=None, help="path to site.yaml (default: inbox/, else inputs/)"
    )
    p_sync.set_defaults(func=_cmd_sync_content)

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

    p_view = sub.add_parser("viewer", help="serve the localhost read+edit data viewer")
    p_view.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    p_view.add_argument("--port", type=int, default=8080, help="bind port (default: 8080)")
    p_view.add_argument("--debug", action="store_true", help="uvicorn debug log level")
    p_view.set_defaults(func=_cmd_viewer)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
