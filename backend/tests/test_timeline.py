"""Unit tests for the timeline builder (LLM faked)."""

from __future__ import annotations

from src.models import Publication, PublicationSet
from src.timeline import build_timeline, most_recent


class FakeLLM:
    def __init__(self, blurb="A short blurb."):
        self.blurb = blurb
        self.calls = 0

    def complete(self, *, system, user, **kw):
        self.calls += 1
        return self.blurb


def _pub(title, year, *, desc=None):
    return Publication(
        id=f"{title.lower()}-{year}", title=title, authors=["A Person"],
        year=year, type="article", description=desc,
    )


def _set(*pubs):
    return PublicationSet(publications=list(pubs))


def test_most_recent_picks_newest_n():
    pubs = [_pub("a", 2019), _pub("b", 2023), _pub("c", 2021), _pub("d", 2022)]
    got = [p.title for p in most_recent(pubs, n=2)]
    assert got == ["b", "d"]  # 2023 then 2022


def test_build_timeline_year_label_and_positions():
    ps = _set(_pub("Newest", 2023), _pub("Older", 2021))
    entries = build_timeline(ps)  # no llm -> reuse description (None here)
    assert [e.position for e in entries] == [0, 1]
    assert entries[0].title == "Newest"
    assert entries[0].date_label == "2023"
    assert entries[0].year == 2023
    assert entries[0].slug == "newest-2023"
    assert entries[0].blurb is None


def test_build_timeline_writes_blurb_with_llm():
    ps = _set(_pub("Paper", 2022))
    llm = FakeLLM("AI blurb")
    entries = build_timeline(ps, llm=llm)
    assert entries[0].blurb == "AI blurb"
    assert llm.calls == 1


def test_build_timeline_reuses_existing_description_without_llm():
    ps = _set(_pub("Paper", 2022, desc="existing text"))
    entries = build_timeline(ps)
    assert entries[0].blurb == "existing text"


def test_build_timeline_caps_at_n():
    ps = _set(*[_pub(f"p{i}", 2000 + i) for i in range(10)])
    assert len(build_timeline(ps, n=5)) == 5


def test_build_timeline_defaults_to_full_history():
    ps = _set(*[_pub(f"p{i}", 2000 + i) for i in range(10)])
    entries = build_timeline(ps)  # n=None -> the whole set
    assert len(entries) == 10
    assert [e.position for e in entries] == list(range(10))
    assert entries[0].year == 2009  # newest first


def test_most_recent_returns_all_when_n_none():
    pubs = [_pub("a", 2019), _pub("b", 2023), _pub("c", 2021)]
    assert [p.title for p in most_recent(pubs)] == ["b", "c", "a"]
