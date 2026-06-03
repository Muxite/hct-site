"""Unit tests for the publication schema and validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import Publication, PublicationSet, PubType, slug_for


def _pub(**over):
    base = dict(
        id="zhu2022-x",
        title="A unified representation",
        authors=["Hongzhi Zhu", "Sidney Fels"],
        year=2022,
        type="article",
        link="https://doi.org/10.1109/JBHI.2022.3150242",
    )
    base.update(over)
    return Publication(**base)


def test_minimal_valid_publication():
    p = _pub()
    assert p.year == 2022
    assert p.type is PubType.article
    assert p.description is None  # optional


def test_authors_must_be_non_empty():
    with pytest.raises(ValidationError):
        _pub(authors=[])
    with pytest.raises(ValidationError):
        _pub(authors=["  ", ""])


def test_authors_are_stripped_and_blank_dropped():
    p = _pub(authors=["  Sidney Fels  ", "", "Nima Ashjaee"])
    assert p.authors == ["Sidney Fels", "Nima Ashjaee"]


@pytest.mark.parametrize("year", [1899, 2101, 0, -5])
def test_year_out_of_range_rejected(year):
    with pytest.raises(ValidationError):
        _pub(year=year)


def test_title_and_id_non_empty():
    with pytest.raises(ValidationError):
        _pub(title="   ")
    with pytest.raises(ValidationError):
        _pub(id="")


def test_link_must_be_http():
    with pytest.raises(ValidationError):
        _pub(link="doi.org/10.1/x")  # no scheme


def test_blank_link_becomes_none():
    assert _pub(link="   ").link is None


def test_unknown_pub_type_rejected():
    with pytest.raises(ValidationError):
        _pub(type="journal-thing")


def test_extra_fields_ignored():
    # LLM may add stray keys; we ignore rather than crash.
    p = Publication(
        id="a2020-x", title="T", authors=["A"], year=2020, hallucinated="oops"
    )
    assert not hasattr(p, "hallucinated")


def test_slug_for_is_stable_and_clean():
    s = slug_for(["Hongzhi Zhu", "Sidney Fels"], 2022, "A unified representation!")
    assert s == "zhu2022-a-unified-representation"
    # deterministic
    assert s == slug_for(["Hongzhi Zhu"], 2022, "A unified representation!")


def test_slug_handles_accents_and_empty_authors():
    assert slug_for(["Émile Zöla"], 2019, "Été") == "zola2019-ete"
    assert slug_for([], 2019, "Title").startswith("anon2019-")


def test_by_year_groups_newest_first():
    ps = PublicationSet(
        publications=[
            _pub(id="a", year=2020),
            _pub(id="b", year=2022),
            _pub(id="c", year=2022),
        ]
    )
    grouped = ps.by_year()
    assert list(grouped.keys()) == [2022, 2020]
    assert len(grouped[2022]) == 2


def test_deduped_keeps_first_occurrence():
    ps = PublicationSet(
        publications=[
            _pub(id="dup", title="first"),
            _pub(id="dup", title="second"),
            _pub(id="unique"),
        ]
    )
    d = ps.deduped()
    ids = [p.id for p in d.publications]
    assert ids == ["dup", "unique"]
    assert d.publications[0].title == "first"


def test_publication_set_defaults():
    ps = PublicationSet()
    assert ps.publications == []
    assert ps.source_fingerprints == {}
    assert ps.generated_at is not None
