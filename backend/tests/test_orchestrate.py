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
