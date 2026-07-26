"""Unit tests for OpenAlex-field enrichment (mocked httpx transport, MockTransport
pattern per test_paper_sources.py; no live API calls)."""

from __future__ import annotations

import httpx

from src.enrich import ENRICH_FIELDS, enrich_publications
from src.paper_sources import PaperSources

# A real-ish OpenAlex Work with everything enrich.py reads.
OPENALEX_WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1111/x.2023",
    "title": "Signal-based control for assistive robotics",
    "display_name": "Signal-based control for assistive robotics",
    "publication_year": 2023,
    "cited_by_count": 17,
    "authorships": [{"author": {"display_name": "A Person"}}],
    "primary_location": {
        "landing_page_url": "https://publisher.example/x",
        "source": {"display_name": "Journal of Examples"},
    },
    "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://oa.example/x.pdf"},
    "concepts": [
        {"display_name": "Robotics", "score": 0.81},
        {"display_name": "Signal processing", "score": 0.9},
        {"display_name": "Assistive technology", "score": 0.5},
        {"display_name": "Human-computer interaction", "score": 0.7},
    ],
}

CROSSREF_ITEM = {
    "DOI": "10.1111/x.2023",
    "title": ["Signal-based control for assistive robotics"],
    "author": [{"given": "A", "family": "Person"}],
    "issued": {"date-parts": [[2023]]},
    "container-title": ["Journal of Examples"],
    "URL": "https://doi.org/10.1111/x.2023",
}


def _row(**over):
    row = {
        "slug": "person2023-signal",
        "title": "Signal-based control for assistive robotics",
        "authors": ["A Person"],
        "year": 2023,
        "link": "https://doi.org/10.1111/x.2023",
        "citation_count": None,
        "concepts": None,
        "oa_status": None,
    }
    row.update(over)
    return row


class _FakeSB:
    """Minimal SupabaseClient stand-in: canned select rows, recorded updates."""

    def __init__(self, rows):
        self.rows = rows
        self.updates: list[tuple[str, dict, dict]] = []

    def select(self, table, *, columns=None, params=None):
        assert table == "publications"
        return self.rows

    def update(self, table, values, *, params):
        self.updates.append((table, dict(values), dict(params)))


def _sources(routes) -> PaperSources:
    transport = httpx.MockTransport(routes)
    return PaperSources(client=httpx.Client(transport=transport))


def _updates_by_field(sb: _FakeSB) -> dict[str, tuple[dict, dict]]:
    """Flatten sb.updates into {field: (values, params)} (enrich writes one
    field per PATCH call, so each update touches exactly one field)."""

    out = {}
    for _, values, params in sb.updates:
        assert len(values) == 1
        (field,) = values
        out[field] = (values, params)
    return out


def test_enrich_writes_all_missing_fields_from_matched_openalex_record():
    def routes(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert request.url.path == "/works/doi:10.1111/x.2023"  # trusted-DOI path
        return httpx.Response(200, json=OPENALEX_WORK)

    sb = _FakeSB([_row()])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 1
    by_field = _updates_by_field(sb)
    assert set(by_field) == set(ENRICH_FIELDS)
    assert by_field["citation_count"][0] == {"citation_count": 17}
    assert by_field["citation_count"][1] == {
        "slug": "eq.person2023-signal",
        "citation_count": "is.null",
    }
    # Top concepts, sorted by score descending (all 4 fit under the cap of 5).
    assert by_field["concepts"][0]["concepts"] == [
        "Signal processing",
        "Robotics",
        "Human-computer interaction",
        "Assistive technology",
    ]
    assert by_field["concepts"][1] == {
        "slug": "eq.person2023-signal",
        "concepts": "is.null",
    }
    assert by_field["oa_status"][0] == {"oa_status": "gold"}
    assert by_field["oa_status"][1] == {
        "slug": "eq.person2023-signal",
        "oa_status": "is.null",
    }


def test_enrich_skips_row_already_fully_enriched_no_discover_call():
    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError("discover() should never be called for a fully-enriched row")

    row = _row(citation_count=5, concepts=["Something"], oa_status="green")
    sb = _FakeSB([row])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 0
    assert sb.updates == []


def test_enrich_only_writes_fields_still_null_on_partially_enriched_row():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OPENALEX_WORK)

    # citation_count already set (by an earlier run/admin) -- must be left alone.
    row = _row(citation_count=999)
    sb = _FakeSB([row])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 1
    by_field = _updates_by_field(sb)
    assert "citation_count" not in by_field  # never touched -- already non-null
    assert set(by_field) == {"concepts", "oa_status"}


def test_enrich_search_path_used_when_link_is_not_a_doi_url():
    """A publisher/landing-page link must not be treated as a DOI."""

    def routes(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert request.url.path == "/works"  # search, not /works/doi:<bogus>
        return httpx.Response(200, json={"results": [OPENALEX_WORK]})

    row = _row(link="https://publisher.example/x")
    sb = _FakeSB([row])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 1
    assert set(_updates_by_field(sb)) == set(ENRICH_FIELDS)


def test_enrich_writes_nothing_when_no_candidates_found():
    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"message": {"items": []}})

    row = _row(link="https://publisher.example/x")
    sb = _FakeSB([row])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 0
    assert sb.updates == []


def test_enrich_writes_nothing_for_crossref_only_match():
    """Crossref carries none of citation_count/concepts/oa_status -- a strong
    Crossref-only match must not fabricate them."""

    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"message": {"items": [CROSSREF_ITEM]}})

    row = _row(link="https://publisher.example/x")
    sb = _FakeSB([row])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 0
    assert sb.updates == []


def test_enrich_rejects_weak_title_match():
    wrong = dict(OPENALEX_WORK, title="Totally unrelated paper", display_name="Totally unrelated paper")

    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [wrong]})
        return httpx.Response(200, json={"message": {"items": []}})

    row = _row(link="https://publisher.example/x")
    sb = _FakeSB([row])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 0
    assert sb.updates == []


def test_enrich_respects_limit():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OPENALEX_WORK)

    rows = [_row(slug=f"p{i}", link=f"https://doi.org/10.1111/x.202{i}") for i in range(3)]
    sb = _FakeSB(rows)
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources, limit=1)

    assert written == 1


def test_enrich_no_rows_is_a_noop():
    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no rows -- discover() should never be called")

    sb = _FakeSB([])
    with _sources(routes) as sources:
        written = enrich_publications(sb, sources)

    assert written == 0
    assert sb.updates == []
