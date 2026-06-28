"""Unit tests for paper link discovery + validation (academic-API MockTransport)."""

from __future__ import annotations

import httpx

from src.paper_sources import (
    PaperSources,
    WorkRecord,
    normalize_title,
    parse_crossref_work,
    parse_openalex_work,
    reconstruct_abstract,
    strip_jats,
    title_similarity,
)

# A real-ish OpenAlex Work, trimmed to the fields we read.
OPENALEX_WORK = {
    "id": "https://openalex.org/W42",
    "doi": "https://doi.org/10.1234/abc.2022",
    "title": "A unified representation of control logic",
    "display_name": "A unified representation of control logic",
    "publication_year": 2022,
    "authorships": [
        {"author": {"display_name": "Hongzhi Zhu"}},
        {"author": {"display_name": "Sidney Fels"}},
    ],
    "primary_location": {
        "landing_page_url": "https://publisher.example/article/42",
        "source": {"display_name": "Journal of Examples"},
    },
    "best_oa_location": {"pdf_url": "https://publisher.example/article/42.pdf"},
    "open_access": {"is_oa": True, "oa_url": "https://oa.example/42.pdf"},
    "abstract_inverted_index": {"We": [0], "study": [1], "control": [2], "logic": [3]},
}

CROSSREF_ITEM = {
    "DOI": "10.1234/abc.2022",
    "title": ["A unified representation of control logic"],
    "author": [{"given": "Hongzhi", "family": "Zhu"}, {"given": "Sidney", "family": "Fels"}],
    "issued": {"date-parts": [[2022, 5]]},
    "container-title": ["Journal of Examples"],
    "URL": "https://doi.org/10.1234/abc.2022",
    "link": [{"URL": "https://publisher.example/full.pdf", "content-type": "application/pdf"}],
    "abstract": "<jats:p>We study <jats:italic>control logic</jats:italic>.</jats:p>",
}


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_reconstruct_abstract_orders_by_position():
    idx = {"world": [1], "hello": [0], "again": [2]}
    assert reconstruct_abstract(idx) == "hello world again"
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_strip_jats_removes_tags():
    assert strip_jats("<jats:p>We study <jats:italic>X</jats:italic>.</jats:p>") == "We study X ."
    assert strip_jats(None) is None
    assert strip_jats("") is None


def test_title_similarity_high_for_same_low_for_different():
    a = "A unified representation of control logic"
    assert title_similarity(a, a) == 1.0
    assert title_similarity(a, "a Unified Representation of Control-Logic!") > 0.9
    assert title_similarity(a, "Deep learning for cat photos") < 0.4
    assert title_similarity(a, "") == 0.0


def test_normalize_title_strips_punct_and_case():
    assert normalize_title("It's a  TEST!!") == "it s a test"


# --------------------------------------------------------------------------- #
# Record parsing
# --------------------------------------------------------------------------- #
def test_parse_openalex_work():
    rec = parse_openalex_work(OPENALEX_WORK)
    assert rec.source == "openalex"
    assert rec.doi == "10.1234/abc.2022"
    assert rec.year == 2022
    assert rec.authors == ["Hongzhi Zhu", "Sidney Fels"]
    assert rec.venue == "Journal of Examples"
    assert rec.landing_url == "https://publisher.example/article/42"
    assert rec.oa_url == "https://oa.example/42.pdf"
    assert rec.abstract == "We study control logic"
    assert rec.canonical_url == "https://doi.org/10.1234/abc.2022"


def test_parse_crossref_work():
    rec = parse_crossref_work(CROSSREF_ITEM)
    assert rec.source == "crossref"
    assert rec.doi == "10.1234/abc.2022"
    assert rec.year == 2022
    assert rec.authors == ["Hongzhi Zhu", "Sidney Fels"]
    assert rec.venue == "Journal of Examples"
    assert rec.oa_url == "https://publisher.example/full.pdf"
    assert "control logic" in rec.abstract


def test_canonical_url_falls_back_to_landing_without_doi():
    rec = WorkRecord(source="x", title="t", landing_url="https://landing")
    assert rec.canonical_url == "https://landing"


# --------------------------------------------------------------------------- #
# Client (MockTransport router)
# --------------------------------------------------------------------------- #
def _sources(routes, *, contact_email="", **kw) -> PaperSources:
    """Build PaperSources whose HTTP calls are answered by ``routes(request)``."""

    transport = httpx.MockTransport(routes)
    http = httpx.Client(transport=transport)
    return PaperSources(
        contact_email=contact_email,
        client=http,
        openalex_base="https://api.openalex.org",
        crossref_base="https://api.crossref.org",
        **kw,
    )


def test_openalex_by_doi_and_mailto_param():
    seen = {}

    def routes(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        assert request.url.host == "api.openalex.org"
        assert request.url.path == "/works/doi:10.1234/abc.2022"
        return httpx.Response(200, json=OPENALEX_WORK)

    with _sources(routes, contact_email="lab@example.com") as s:
        rec = s.openalex_by_doi("https://doi.org/10.1234/abc.2022")
    assert rec.title.startswith("A unified")
    assert "mailto=lab%40example.com" in seen["url"]


def test_discover_with_known_doi_is_trusted_and_enriched():
    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json=OPENALEX_WORK)
        return httpx.Response(404)

    with _sources(routes) as s:
        res = s.discover(title="A unified representation of control logic", year=2022, doi="10.1234/abc.2022")
    assert res.matched is True
    assert res.canonical_url == "https://doi.org/10.1234/abc.2022"
    assert res.oa_url == "https://oa.example/42.pdf"
    assert res.abstract == "We study control logic"
    assert "trusted" in res.reason


def test_discover_by_search_accepts_strong_match():
    def routes(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert request.url.path == "/works"
        return httpx.Response(200, json={"results": [OPENALEX_WORK]})

    with _sources(routes) as s:
        res = s.discover(title="A unified representation of control logic", year=2022)
    assert res.matched is True
    assert res.confidence > 0.9
    assert res.canonical_url == "https://doi.org/10.1234/abc.2022"


def test_discover_rejects_wrong_title():
    wrong = dict(OPENALEX_WORK, title="Deep learning for cat photos", display_name="Deep learning for cat photos")

    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [wrong]})
        return httpx.Response(200, json={"message": {"items": []}})

    with _sources(routes) as s:
        res = s.discover(title="A unified representation of control logic", year=2022)
    assert res.matched is False
    assert res.canonical_url is None  # never attach a weak match
    assert res.record is not None  # but the candidate is still inspectable
    assert "rejected" in res.reason


def test_discover_rejects_year_mismatch():
    old = dict(OPENALEX_WORK, publication_year=2005)

    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [old]})
        return httpx.Response(200, json={"message": {"items": []}})

    with _sources(routes) as s:
        res = s.discover(title="A unified representation of control logic", year=2022)
    assert res.matched is False
    assert "year" in res.reason


def test_discover_falls_back_to_crossref_when_openalex_empty():
    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"message": {"items": [CROSSREF_ITEM]}})

    with _sources(routes) as s:
        res = s.discover(title="A unified representation of control logic", year=2022)
    assert res.matched is True
    assert res.record.source == "crossref"
    assert res.canonical_url == "https://doi.org/10.1234/abc.2022"


def test_pmcid_for_and_pmc_fulltext():
    body = "<article><body><p>" + ("real full text body. " * 60) + "</p></body></article>"

    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ebi.ac.uk":  # Europe PMC search -> pmcid
            return httpx.Response(200, json={"resultList": {"result": [{"pmcid": "PMC999"}]}})
        if request.url.host == "eutils.ncbi.nlm.nih.gov":  # NCBI efetch -> JATS XML
            assert request.url.params["id"] == "999"
            return httpx.Response(200, text=body)
        return httpx.Response(404)

    with _sources(routes) as s:
        assert s.pmcid_for("10.1/x") == "PMC999"
        text = s.fulltext_by_doi("10.1/x")
    assert text and "real full text body" in text
    assert "<" not in text  # tags stripped


def test_pmc_fulltext_rejects_short_stub():
    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ebi.ac.uk":
            return httpx.Response(200, json={"resultList": {"result": [{"pmcid": "PMC1"}]}})
        return httpx.Response(200, text="<error>not open access</error>")  # short stub

    with _sources(routes) as s:
        assert s.fulltext_by_doi("10.1/x") is None


def test_fulltext_by_doi_none_when_no_pmcid():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resultList": {"result": []}})

    with _sources(routes) as s:
        assert s.fulltext_by_doi("10.1/x") is None


def test_discover_no_candidates():
    def routes(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"message": {"items": []}})

    with _sources(routes) as s:
        res = s.discover(title="Totally unknown paper", year=2022)
    assert res.matched is False
    assert res.canonical_url is None
    assert res.record is None
