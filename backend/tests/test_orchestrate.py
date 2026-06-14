"""End-to-end orchestration tests with everything faked (no network/LLM)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src import orchestrate
from src.config import Config
from src.state import StateStore
from src.ujin_client import ScrapeResult


# --- fakes ----------------------------------------------------------------

class FakeUjin:
    """Returns a canned ScrapeResult per URL; fingerprints are mutable."""

    def __init__(self, by_url):
        self.by_url = by_url  # url -> (fingerprint, text)

    def scrape(self, url, *, mode="article", force_refresh=False):
        fp, text = self.by_url[url]
        return ScrapeResult(
            url=url, kind="article", fingerprint=fp, text=text,
            used_renderer=False, strategy_used="http",
        )


class FakeSupabase:
    """Records upsert/replace calls so tests can assert what was published."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.upserts: list[str] = []

    def upsert(self, table, rows, *, on_conflict=None):
        self.upserts.append(table)
        self.tables.setdefault(table, [])
        self.tables[table].extend(rows)
        return len(rows)

    def replace(self, table, rows, *, key):
        self.tables[table] = list(rows)
        return len(rows)


class FakeLLM:
    """Maps page text -> publications JSON; counts calls."""

    def __init__(self, by_text):
        self.by_text = by_text
        self.calls = 0

    def complete(self, *, system, user, **kw):
        self.calls += 1
        for needle, pubs in self.by_text.items():
            if needle in user:
                return json.dumps({"publications": pubs})
        return json.dumps({"publications": []})


FELS_URL = "https://scholar.example/fels"
ASH_URL = "https://scholar.example/ashjaee"

FELS_PUBS = [
    {"title": "Shared Paper", "authors": ["Sidney Fels", "Nima Ashjaee"], "year": 2022, "type": "article"},
    {"title": "Fels Only", "authors": ["Sidney Fels"], "year": 2021, "type": "inproceedings"},
]
ASH_PUBS = [
    {"title": "Shared Paper", "authors": ["Sidney Fels", "Nima Ashjaee"], "year": 2022, "type": "article"},
    {"title": "Ashjaee Only", "authors": ["Nima Ashjaee"], "year": 2023, "type": "preprint"},
]


@pytest.fixture
def cfg(tmp_path):
    assets = tmp_path / "assets"
    (assets / "sources").mkdir(parents=True)
    (assets / "state").mkdir(parents=True)
    (assets / "sources" / "sources.yaml").write_text(
        f"sources:\n"
        f"  - {{key: fels, member: Sidney Fels, url: '{FELS_URL}'}}\n"
        f"  - {{key: ashjaee, member: Nima Ashjaee, url: '{ASH_URL}'}}\n",
        encoding="utf-8",
    )
    return Config(openrouter_api_key="x", data_dir=assets)


def _ujin(fels_fp="fp-fels-1", ash_fp="fp-ash-1"):
    return FakeUjin({FELS_URL: (fels_fp, "FELS PAGE"), ASH_URL: (ash_fp, "ASH PAGE")})


def _llm():
    return FakeLLM({"FELS PAGE": FELS_PUBS, "ASH PAGE": ASH_PUBS})


# --- tests ----------------------------------------------------------------

def test_first_run_extracts_all_and_merges_deduped(cfg):
    state = StateStore(cfg.state_dir)
    sb = FakeSupabase()
    result = orchestrate.run(cfg, llm=_llm(), ujin=_ujin(), supabase=sb, state=state)

    assert result.changed is True
    assert sorted(result.sources_changed) == ["ashjaee", "fels"]
    # Shared Paper deduped: 2 + 2 - 1 = 3 unique
    assert result.total_publications == 3
    # publications were upserted (keyed by slug) to Supabase
    titles = sorted(r["title"] for r in sb.tables["publications"])
    assert titles == ["Ashjaee Only", "Fels Only", "Shared Paper"]
    assert "slug" in sb.tables["publications"][0]
    # timeline rebuilt from the 5 (here 3) most recent, newest first
    assert result.timeline_entries == 3
    tl = sb.tables["timeline"]
    assert tl[0]["year"] == 2023 and tl[0]["position"] == 0
    assert tl[0]["date_label"] == "2023"


def test_second_run_unchanged_is_noop(cfg):
    state = StateStore(cfg.state_dir)
    orchestrate.run(cfg, llm=_llm(), ujin=_ujin(), supabase=FakeSupabase(), state=state)

    llm2 = _llm()
    sb = FakeSupabase()
    result = orchestrate.run(cfg, llm=llm2, ujin=_ujin(), supabase=sb, state=state)
    assert result.changed is False
    assert result.sources_changed == []
    assert llm2.calls == 0  # no LLM work when nothing changed
    assert sb.tables == {}  # nothing published


def test_changed_source_reextracts_only_that_one(cfg):
    state = StateStore(cfg.state_dir)
    orchestrate.run(cfg, llm=_llm(), ujin=_ujin(), supabase=FakeSupabase(), state=state)

    # Fels page changes; Ashjaee unchanged.
    llm2 = _llm()
    ujin2 = _ujin(fels_fp="fp-fels-2")
    sb = FakeSupabase()
    result = orchestrate.run(cfg, llm=llm2, ujin=ujin2, supabase=sb, state=state)
    assert result.changed is True
    assert result.sources_changed == ["fels"]
    assert llm2.calls == 1  # only the changed source hit the LLM
    # merged set still complete (ashjaee pubs came from cache)
    assert result.total_publications == 3
    assert len(sb.tables["publications"]) == 3


def test_force_reextracts_everything(cfg):
    state = StateStore(cfg.state_dir)
    orchestrate.run(cfg, llm=_llm(), ujin=_ujin(), supabase=FakeSupabase(), state=state)

    llm2 = _llm()
    result = orchestrate.run(
        cfg, llm=llm2, ujin=_ujin(), supabase=FakeSupabase(), state=state, force=True
    )
    assert result.changed is True
    assert sorted(result.sources_changed) == ["ashjaee", "fels"]
    assert llm2.calls == 2


def test_style_profile_is_NOT_sent_during_extraction(cfg, tmp_path):
    # Descriptions/style are the separate `describe` step; extraction must not
    # pay for the style profile even when one is saved.
    (cfg.state_dir / "style_profile.txt").write_text("terse, active voice", encoding="utf-8")
    captured = []

    class CapturingLLM(FakeLLM):
        def complete(self, *, system, user, **kw):
            captured.append(user)
            return super().complete(system=system, user=user, **kw)

    llm = CapturingLLM({"FELS PAGE": FELS_PUBS, "ASH PAGE": ASH_PUBS})
    orchestrate.run(
        cfg, llm=llm, ujin=_ujin(), supabase=FakeSupabase(), state=StateStore(cfg.state_dir)
    )
    assert captured  # extraction did run
    assert all("terse, active voice" not in u for u in captured)


def test_load_sources_validates(tmp_path):
    bad = tmp_path / "s.yaml"
    bad.write_text("sources:\n  - {member: x}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        orchestrate.load_sources(bad)


def test_load_sources_accepts_path_sources(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("sources:\n  - {key: cv, path: inputs/cv.docx}\n", encoding="utf-8")
    [src] = orchestrate.load_sources(f)
    assert src.path == "inputs/cv.docx" and src.url is None


# --- Scholar / obscura branch ---------------------------------------------

SCHOLAR_URL = "https://scholar.google.com/citations?user=bf7ilxMAAAAJ&hl=en"


class FakeObscura:
    """Stand-in renderer: records the URL it was asked to render."""

    def __init__(self, text="SCHOLAR PROFILE TEXT", *, ok=True):
        self._text = text
        self._ok = ok
        self.rendered: list[str] = []

    def available(self):
        return self._ok

    def render_text(self, url):
        self.rendered.append(url)
        if not self._text:
            from src.obscura_client import ObscuraError
            raise ObscuraError("empty render")
        return self._text


@pytest.fixture
def scholar_cfg(tmp_path):
    assets = tmp_path / "assets"
    (assets / "sources").mkdir(parents=True)
    (assets / "state").mkdir(parents=True)
    (assets / "sources" / "sources.yaml").write_text(
        f"sources:\n  - {{key: fels, member: Sidney Fels, url: '{SCHOLAR_URL}'}}\n",
        encoding="utf-8",
    )
    # Scholar is opt-in: these tests exercise the *enabled* Scholar path.
    return Config(openrouter_api_key="x", data_dir=assets, scholar_enabled=True)


def test_scholar_source_renders_via_obscura_and_normalizes_url(scholar_cfg):
    obs = FakeObscura()
    llm = FakeLLM({"SCHOLAR PROFILE TEXT": FELS_PUBS})
    sb = FakeSupabase()
    result = orchestrate.run(
        scholar_cfg, llm=llm, ujin=_ujin(), supabase=sb, obscura=obs,
        state=StateStore(scholar_cfg.state_dir),
    )
    assert result.changed is True and result.sources_changed == ["fels"]
    assert llm.calls == 1
    # ujin was never consulted for the Scholar profile; obscura got a normalized URL.
    assert len(obs.rendered) == 1
    assert "pagesize=100" in obs.rendered[0] and "sortby=pubdate" in obs.rendered[0]
    assert len(sb.tables["publications"]) == 2


def test_scholar_source_skipped_when_obscura_unavailable(scholar_cfg):
    llm = FakeLLM({"SCHOLAR PROFILE TEXT": FELS_PUBS})
    sb = FakeSupabase()
    result = orchestrate.run(
        scholar_cfg, llm=llm, ujin=_ujin(), supabase=sb,
        obscura=FakeObscura(ok=False), state=StateStore(scholar_cfg.state_dir),
    )
    # No render, no extraction, nothing published — never a partial/invented page.
    assert llm.calls == 0
    assert result.changed is False
    assert sb.tables == {}


# --- CV sources --------------------------------------------------------------

SCRAPED_PUBS = [
    {"title": "Shared Paper", "authors": ["Sidney Fels"], "year": 2022,
     "type": "article", "venue": "Scholar Venue"},
    {"title": "Fels Only", "authors": ["Sidney Fels"], "year": 2021, "type": "inproceedings"},
]
CV_PUBS = [
    {"title": "Shared Paper", "authors": ["Sidney Fels"], "year": 2022,
     "type": "article", "venue": "CV Venue"},
    {"title": "CV Only", "authors": ["Sidney Fels"], "year": 2018, "type": "techreport"},
]


@pytest.fixture
def cv_cfg(tmp_path):
    assets = tmp_path / "assets"
    (assets / "sources").mkdir(parents=True)
    (assets / "state").mkdir(parents=True)
    (assets / "inputs").mkdir(parents=True)
    (assets / "inputs" / "fels-cv.txt").write_text(
        "biography preamble\nPublications Record\nCV PAGE TEXT", encoding="utf-8"
    )
    # The scraped source is listed FIRST to prove CV-wins is by source kind,
    # not yaml order.
    (assets / "sources" / "sources.yaml").write_text(
        f"sources:\n"
        f"  - {{key: fels, member: Sidney Fels, url: '{FELS_URL}'}}\n"
        f"  - {{key: fels-cv, member: Sidney Fels, path: inputs/fels-cv.txt}}\n",
        encoding="utf-8",
    )
    return Config(openrouter_api_key="x", data_dir=assets)


def _cv_llm():
    return FakeLLM({"CV PAGE TEXT": CV_PUBS, "FELS PAGE": SCRAPED_PUBS})


def test_cv_source_extracts_and_cv_wins_dedupe(cv_cfg):
    llm = _cv_llm()
    sb = FakeSupabase()
    result = orchestrate.run(
        cv_cfg, llm=llm, ujin=_ujin(), supabase=sb, state=StateStore(cv_cfg.state_dir)
    )
    assert result.changed is True
    assert sorted(result.sources_changed) == ["fels", "fels-cv"]
    pubs = {r["title"]: r for r in sb.tables["publications"]}
    assert set(pubs) == {"Shared Paper", "Fels Only", "CV Only"}
    # Both sources are valid, but the CV is primary: on a shared paper the
    # CV's metadata wins — even though the scraped source comes first in
    # sources.yaml.
    assert pubs["Shared Paper"]["venue"] == "CV Venue"


def test_cv_run_populates_parse_tracker(cv_cfg):
    from src.metrics import ParseTracker

    tracker = ParseTracker()
    orchestrate.run(
        cv_cfg, llm=_cv_llm(), ujin=_ujin(), supabase=FakeSupabase(),
        state=StateStore(cv_cfg.state_dir), parse_tracker=tracker,
    )
    # The fixture CV is one unparseable entry -> recovered via LLM fallback.
    s = tracker.summary
    assert s["total"] == 1 and s["llm"] == 1


def test_run_result_carries_parse_summary(cv_cfg):
    from src.metrics import ParseTracker

    result = orchestrate.run(
        cv_cfg, llm=_cv_llm(), ujin=_ujin(), supabase=FakeSupabase(),
        state=StateStore(cv_cfg.state_dir), parse_tracker=ParseTracker(),
    )
    assert result.parse_summary["total"] == 1


def test_inbox_cv_overrides_inputs_copy(cv_cfg):
    (cv_cfg.data_dir / "inbox").mkdir()
    (cv_cfg.data_dir / "inbox" / "fels-cv.txt").write_text(
        "Publications Record\nINBOX CV TEXT", encoding="utf-8"
    )
    captured = []

    class CapturingLLM(FakeLLM):
        def complete(self, *, system, user, **kw):
            captured.append(user)
            return super().complete(system=system, user=user, **kw)

    llm = CapturingLLM({"INBOX CV TEXT": CV_PUBS, "FELS PAGE": SCRAPED_PUBS})
    result = orchestrate.run(
        cv_cfg, llm=llm, ujin=_ujin(), supabase=FakeSupabase(),
        state=StateStore(cv_cfg.state_dir),
    )
    # The dropped-in file was read instead of inputs/fels-cv.txt.
    assert result.changed is True
    assert any("INBOX CV TEXT" in u for u in captured)
    assert all("CV PAGE TEXT" not in u for u in captured)


def test_cv_unchanged_is_noop_then_file_edit_reextracts(cv_cfg):
    state = StateStore(cv_cfg.state_dir)
    orchestrate.run(cv_cfg, llm=_cv_llm(), ujin=_ujin(), supabase=FakeSupabase(), state=state)

    # Untouched CV (and pages) -> no LLM work, nothing published.
    llm2 = _cv_llm()
    result = orchestrate.run(cv_cfg, llm=llm2, ujin=_ujin(), supabase=FakeSupabase(), state=state)
    assert result.changed is False and llm2.calls == 0

    # Editing the CV file changes its fingerprint -> only the CV re-extracts.
    (cv_cfg.data_dir / "inputs" / "fels-cv.txt").write_text(
        "Publications Record\nCV PAGE TEXT (revised)", encoding="utf-8"
    )
    llm3 = _cv_llm()
    result = orchestrate.run(cv_cfg, llm=llm3, ujin=_ujin(), supabase=FakeSupabase(), state=state)
    assert result.changed is True
    assert result.sources_changed == ["fels-cv"]
    assert llm3.calls == 1


def test_missing_cv_file_skips_and_keeps_cache(cv_cfg):
    state = StateStore(cv_cfg.state_dir)
    orchestrate.run(cv_cfg, llm=_cv_llm(), ujin=_ujin(), supabase=FakeSupabase(), state=state)

    (cv_cfg.data_dir / "inputs" / "fels-cv.txt").unlink()
    llm2 = _cv_llm()
    result = orchestrate.run(
        cv_cfg, llm=llm2, ujin=_ujin(), supabase=FakeSupabase(), state=state, force=True
    )
    # The CV source is skipped (no invented extraction) but its cached pubs
    # still flow into the merged set.
    assert "fels-cv" not in result.sources_changed
    assert llm2.calls == 1  # only the scraped source hit the LLM
    assert result.total_publications == 3


def test_cv_extraction_skips_preamble_before_publications(cv_cfg):
    captured = []

    class CapturingLLM(FakeLLM):
        def complete(self, *, system, user, **kw):
            captured.append(user)
            return super().complete(system=system, user=user, **kw)

    llm = CapturingLLM({"CV PAGE TEXT": CV_PUBS, "FELS PAGE": SCRAPED_PUBS})
    orchestrate.run(
        cv_cfg, llm=llm, ujin=_ujin(), supabase=FakeSupabase(),
        state=StateStore(cv_cfg.state_dir),
    )
    assert captured
    assert all("biography preamble" not in u for u in captured)


def test_scholar_source_skipped_on_render_error_keeps_cache(scholar_cfg):
    state = StateStore(scholar_cfg.state_dir)
    # First run populates the cache.
    orchestrate.run(
        scholar_cfg, llm=FakeLLM({"SCHOLAR PROFILE TEXT": FELS_PUBS}),
        ujin=_ujin(), supabase=FakeSupabase(), obscura=FakeObscura(), state=state,
    )
    # Second run: render fails -> reuse cached pubs, no new LLM call.
    llm2 = FakeLLM({"SCHOLAR PROFILE TEXT": FELS_PUBS})
    sb = FakeSupabase()
    result = orchestrate.run(
        scholar_cfg, llm=llm2, ujin=_ujin(), supabase=sb,
        obscura=FakeObscura(text="", ok=True), state=state, force=True,
    )
    assert llm2.calls == 0  # render failed -> no extraction
    # cached fels pubs still flow through to the merged set
    assert result.total_publications == 2


# --- Scholar gate (disabled by default) --------------------------------------


def test_scholar_disabled_by_default_never_renders(scholar_cfg):
    cfg_off = Config(openrouter_api_key="x", data_dir=scholar_cfg.data_dir)
    assert cfg_off.scholar_enabled is False
    obs = FakeObscura()
    llm = FakeLLM({"SCHOLAR PROFILE TEXT": FELS_PUBS})
    result = orchestrate.run(
        cfg_off, llm=llm, ujin=_ujin(), supabase=FakeSupabase(),
        obscura=obs, state=StateStore(cfg_off.state_dir),
    )
    # Nothing touched scholar.google.* and no LLM call was made.
    assert obs.rendered == []
    assert llm.calls == 0
    assert result.changed is False


def test_scholar_disabled_keeps_cached_pubs(scholar_cfg):
    state = StateStore(scholar_cfg.state_dir)
    # First run with Scholar enabled populates the cache.
    orchestrate.run(
        scholar_cfg, llm=FakeLLM({"SCHOLAR PROFILE TEXT": FELS_PUBS}),
        ujin=_ujin(), supabase=FakeSupabase(), obscura=FakeObscura(), state=state,
    )
    # Later runs with Scholar back off still publish the cached papers.
    cfg_off = Config(openrouter_api_key="x", data_dir=scholar_cfg.data_dir)
    result = orchestrate.run(
        cfg_off, llm=FakeLLM({}), ujin=_ujin(), supabase=FakeSupabase(),
        obscura=FakeObscura(), state=state, force=True,
    )
    assert result.total_publications == 2


def test_load_sources_explicit_enabled_wins(tmp_path):
    p = tmp_path / "sources.yaml"
    p.write_text(
        "sources:\n"
        "  - {key: a, url: 'https://scholar.google.com/citations?user=X', enabled: true}\n"
        "  - {key: b, url: 'https://example.com/page', enabled: false}\n"
        "  - {key: c, path: inputs/cv.docx}\n",
        encoding="utf-8",
    )
    srcs = {s.key: s for s in orchestrate.load_sources(p, scholar_enabled=False)}
    assert srcs["a"].enabled is True   # explicit flag beats the Scholar default
    assert srcs["b"].enabled is False  # explicit off for an ordinary page
    assert srcs["c"].enabled is True   # CV sources default on


def test_load_sources_scholar_defaults_off(tmp_path):
    p = tmp_path / "sources.yaml"
    p.write_text(
        "sources:\n"
        "  - {key: a, url: 'https://scholar.google.com/citations?user=X'}\n"
        "  - {key: b, url: 'https://example.com/page'}\n",
        encoding="utf-8",
    )
    srcs = {s.key: s for s in orchestrate.load_sources(p)}
    assert srcs["a"].enabled is False
    assert srcs["b"].enabled is True
    srcs_on = {s.key: s for s in orchestrate.load_sources(p, scholar_enabled=True)}
    assert srcs_on["a"].enabled is True
