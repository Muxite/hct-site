"""Unit tests for the CLI: argument parsing + command dispatch (deps stubbed)."""

from __future__ import annotations

import pytest

from src import cli
from src.config import Config
from src.orchestrate import RunResult


def test_parser_run_force():
    args = cli.build_parser().parse_args(["run", "--force"])
    assert args.command == "run" and args.force is True


def test_parser_run_default_no_force():
    args = cli.build_parser().parse_args(["run"])
    assert args.force is False


def test_parser_analyze_style():
    args = cli.build_parser().parse_args(["analyze-style", "cv.docx", "--save"])
    assert args.path == "cv.docx" and args.save is True


def test_parser_sync_content_defaults():
    args = cli.build_parser().parse_args(["sync-content"])
    assert args.command == "sync-content"
    assert args.people is None and args.research is None and args.site is None


def test_parser_sync_content_paths():
    args = cli.build_parser().parse_args(
        ["sync-content", "--people", "/x/p.yaml", "--research", "/x/r.yaml",
         "--site", "/x/s.yaml"]
    )
    assert args.people == "/x/p.yaml" and args.research == "/x/r.yaml"
    assert args.site == "/x/s.yaml"


def test_parser_import_html_removed():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["import-html"])


def test_parser_describe_flags():
    args = cli.build_parser().parse_args(["describe", "--all", "--fetch", "--limit", "5"])
    assert args.command == "describe"
    assert args.all is True and args.fetch is True and args.limit == 5


def test_parser_describe_defaults():
    args = cli.build_parser().parse_args(["describe"])
    assert args.all is False and args.fetch is False and args.limit is None


def test_parser_qa_defaults():
    args = cli.build_parser().parse_args(["qa"])
    assert args.command == "qa"
    assert args.out is None and args.no_source_check is False and args.strict is False


def test_parser_qa_flags():
    args = cli.build_parser().parse_args(
        ["qa", "--out", "/tmp/r.txt", "--no-source-check", "--strict"]
    )
    assert args.out == "/tmp/r.txt" and args.no_source_check is True and args.strict is True


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


class _NullCtx:
    """Stand-in for UjinClient/OpenRouterClient context managers."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def health(self):
        return True


def _patch_common(monkeypatch):
    monkeypatch.setattr(Config, "from_env", classmethod(lambda cls: Config(openrouter_api_key="k")))
    monkeypatch.setattr(cli, "UjinClient", lambda *a, **k: _NullCtx())
    monkeypatch.setattr(cli, "_make_llm", lambda cfg, tracker=None: _NullCtx())
    monkeypatch.setattr(cli, "_make_supabase", lambda cfg: _NullCtx())


def test_run_command_reports_changes(monkeypatch, capsys):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "src.orchestrate.run",
        lambda cfg, **kw: RunResult(
            changed=True, sources_changed=["fels"], total_publications=7,
            timeline_entries=5,
        ),
    )
    rc = cli.main(["run"])
    assert rc == 0
    assert "7 publications" in capsys.readouterr().out


def test_run_command_reports_noop(monkeypatch, capsys):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "src.orchestrate.run",
        lambda cfg, **kw: RunResult(changed=False, sources_processed=["fels", "ashjaee"]),
    )
    rc = cli.main(["run"])
    assert rc == 0
    assert "nothing written" in capsys.readouterr().out


def test_run_command_prints_parse_summary(monkeypatch, capsys, tmp_path):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        Config, "from_env",
        classmethod(lambda cls: Config(openrouter_api_key="k", data_dir=tmp_path)),
    )

    def fake_run(cfg, *, parse_tracker=None, **kw):
        from src.cv_parse import ParseOutcome

        parse_tracker.record(ParseOutcome(
            path="deterministic", section="journal", slug="x2020-y", entry_preview="X",
        ))
        parse_tracker.record(ParseOutcome(
            path="llm", section="other", slug="z2021-w", entry_preview="Z",
        ))
        return RunResult(changed=True, sources_changed=["cv"], total_publications=2,
                         timeline_entries=2)

    monkeypatch.setattr("src.orchestrate.run", fake_run)
    rc = cli.main(["run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cv parse: 2 entries" in out
    assert "1 via LLM fallback" in out
    # per-entry + per-run observability persisted
    assert (tmp_path / "state" / "parse-report.jsonl").exists()
    assert (tmp_path / "state" / "parse-summary.jsonl").exists()


class _FakeSupabase:
    """Context-manager stand-in for SupabaseClient with canned select rows."""

    def __init__(self, rows):
        self._rows = rows
        self.replaced = {}
        self.upserted = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def select(self, table, **kw):
        return self._rows.get(table, [])

    def replace(self, table, rows, *, key):
        rows = list(rows)
        self.replaced[table] = rows
        return len(rows)

    def upsert(self, table, rows, *, on_conflict=None):
        rows = list(rows)
        self.upserted[table] = rows
        return len(rows)


def test_sync_content_command(monkeypatch, capsys, tmp_path):
    _patch_common(monkeypatch)
    (tmp_path / "people.yaml").write_text(
        "people:\n  - name: A\n    status: current\n  - name: B\n    status: alumni\n",
        encoding="utf-8",
    )
    (tmp_path / "research.yaml").write_text(
        "research:\n  - title: Brain2Speech\n    status: current\n"
        "  - title: Old\n    status: archived\n",
        encoding="utf-8",
    )
    (tmp_path / "site.yaml").write_text(
        "site:\n  title: HCT Lab\nsections:\n  vision:\n    title: Vision\n    text: Communicate.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        Config, "from_env",
        classmethod(lambda cls: Config(openrouter_api_key="k", data_dir=tmp_path)),
    )
    sb = _FakeSupabase({})
    monkeypatch.setattr(cli, "_make_supabase", lambda cfg: sb)
    rc = cli.main([
        "sync-content",
        "--people", str(tmp_path / "people.yaml"),
        "--research", str(tmp_path / "research.yaml"),
        "--site", str(tmp_path / "site.yaml"),
    ])
    assert rc == 0
    assert "2 people" in capsys.readouterr().out
    assert sb.replaced["people"][1]["kind"] == "alumni"
    assert sb.replaced["research"][1]["kind"] == "archived"
    keys = {r["key"] for r in sb.upserted["site_content"]}
    assert "vision" in keys and "site_meta" in keys


def test_qa_command_writes_report(monkeypatch, capsys, tmp_path):
    _patch_common(monkeypatch)
    rows = {
        "publications": [
            {"slug": "a", "title": "T", "authors": ["X"], "year": 2022, "type": "article",
             "venue": "V", "link": "https://x", "description": "A fine two-sentence blurb. It matters."},
        ],
        "timeline": [], "people": [], "research": [], "site_content": [],
    }
    monkeypatch.setattr(cli, "_make_supabase", lambda cfg: _FakeSupabase(rows))
    out = tmp_path / "qa.txt"
    rc = cli.main(["qa", "--no-source-check", "--out", str(out)])
    assert rc == 0
    assert "DATA QA REPORT" in capsys.readouterr().out
    assert out.exists() and "SUMMARY" in out.read_text()


def test_qa_command_nonzero_on_error(monkeypatch, capsys, tmp_path):
    _patch_common(monkeypatch)
    dup = {"slug": "a", "title": "T", "authors": ["X"], "year": 2022, "type": "article",
           "link": "https://x", "description": "A fine two-sentence blurb here. It matters a lot."}
    rows = {"publications": [dup, dup], "timeline": [], "people": [], "research": [], "site_content": []}
    monkeypatch.setattr(cli, "_make_supabase", lambda cfg: _FakeSupabase(rows))
    rc = cli.main(["qa", "--no-source-check", "--out", str(tmp_path / "qa.txt")])
    assert rc == 1


def test_health_command(monkeypatch, capsys):
    _patch_common(monkeypatch)
    rc = cli.main(["health"])
    assert rc == 0
    assert "OK" in capsys.readouterr().out
