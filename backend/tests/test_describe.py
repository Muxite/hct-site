"""Unit tests for the opt-in description writer (LLM faked — no network)."""

from __future__ import annotations

from src.describe import (
    build_describe_prompt,
    describe_set,
)
from src.models import Publication, PublicationSet


class FakeLLM:
    """Returns a canned blurb; records prompts and that json_mode is off."""

    def __init__(self, blurb="A neat result."):
        self.blurb = blurb
        self.calls: list[dict] = []

    def complete(self, *, system, user, **kw):
        self.calls.append({"system": system, "user": user, "kw": kw})
        return self.blurb


def _pub(id_, *, description=None, link=None):
    return Publication(
        id=id_, title=f"Title {id_}", authors=["A Person"], year=2022,
        type="article", venue="Venue", link=link, description=description,
    )


def test_build_prompt_includes_style_metadata_and_source():
    pub = _pub("a", link="https://example.org/a")
    prompt = build_describe_prompt(pub, style_profile="terse, active", source_text="ABSTRACT")
    assert "terse, active" in prompt
    assert "Title a" in prompt
    assert "A Person" in prompt
    assert "ABSTRACT" in prompt


def test_describe_set_fills_only_missing_by_default():
    ps = PublicationSet(publications=[
        _pub("a"),
        _pub("b", description="already written"),
    ])
    llm = FakeLLM("written blurb")
    n = describe_set(ps, llm=llm, style_profile="")
    assert n == 1  # only the missing one
    assert ps.publications[0].description == "written blurb"
    assert ps.publications[1].description == "already written"  # untouched
    # free-text mode, never JSON
    assert llm.calls[0]["kw"].get("json_mode") is False


def test_describe_set_all_rewrites_everything_with_limit():
    ps = PublicationSet(publications=[_pub("a"), _pub("b", description="old"), _pub("c")])
    llm = FakeLLM("new")
    n = describe_set(ps, llm=llm, style_profile="", only_missing=False, limit=2)
    assert n == 2
    assert [p.description for p in ps.publications] == ["new", "new", None]


def test_describe_set_uses_fetch_for_grounding_and_tolerates_failure():
    ps = PublicationSet(publications=[
        _pub("a", link="https://example.org/a"),
        _pub("b", link="https://example.org/b"),
        _pub("c"),  # no link -> no fetch
    ])
    seen: list[str] = []

    def fetch(link):
        seen.append(link)
        if link.endswith("/b"):
            raise RuntimeError("scrape failed")
        return "GROUNDING TEXT"

    llm = FakeLLM("blurb")
    n = describe_set(ps, llm=llm, style_profile="", fetch=fetch)
    assert n == 3
    assert seen == ["https://example.org/a", "https://example.org/b"]  # only linked
    # paper a got grounding text in its prompt; b fell back to metadata-only
    assert "GROUNDING TEXT" in llm.calls[0]["user"]
    assert "GROUNDING TEXT" not in llm.calls[1]["user"]
