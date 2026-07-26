"""Unit tests for best-effort figure extraction (PyMuPDF, mocked httpx).

PDF fetch and Storage upload go over ``httpx.MockTransport`` (matching
``test_enrich.py``'s pattern; no live network calls). PyMuPDF itself is
exercised for real against tiny synthetic PDFs built in-memory with PyMuPDF's
own writer API (``_make_pdf``/``_solid_image_bytes`` below) -- this proves the
actual extraction logic (largest-image selection, the min-dimension floor,
``max_pages`` scoping, corrupt-input handling) rather than merely asserting
that mocked functions were called. Nothing here downloads a real PDF or reads
one from disk.
"""

from __future__ import annotations

import fitz
import httpx
import pytest

from src import figures
from src.paper_sources import PaperSources

# A real-ish OpenAlex Work carrying an OA pdf link, matching test_enrich.py's fixture shape.
OPENALEX_WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1111/x.2023",
    "title": "Signal-based control for assistive robotics",
    "display_name": "Signal-based control for assistive robotics",
    "publication_year": 2023,
    "authorships": [{"author": {"display_name": "A Person"}}],
    "primary_location": {
        "landing_page_url": "https://publisher.example/x",
        "source": {"display_name": "Journal of Examples"},
    },
    "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://oa.example/x.pdf"},
}


def _row(**over):
    row = {
        "slug": "person2023-signal",
        "title": "Signal-based control for assistive robotics",
        "authors": ["A Person"],
        "year": 2023,
        "link": "https://doi.org/10.1111/x.2023",
        "project_slug": "brain2speech",
        "image": None,
    }
    row.update(over)
    return row


class _FakeSB:
    """Minimal SupabaseClient stand-in: canned select rows, recorded updates."""

    def __init__(self, rows):
        self.rows = rows
        self.updates: list[tuple[str, dict, dict]] = []
        self.select_calls: list[tuple[str, str | None, dict | None]] = []

    def select(self, table, *, columns=None, params=None):
        assert table == "publications"
        self.select_calls.append((table, columns, params))
        return self.rows

    def update(self, table, values, *, params):
        self.updates.append((table, dict(values), dict(params)))


def _sources(routes) -> PaperSources:
    transport = httpx.MockTransport(routes)
    return PaperSources(client=httpx.Client(transport=transport))


def _no_calls_client() -> httpx.Client:
    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")

    return httpx.Client(transport=httpx.MockTransport(routes))


# --------------------------------------------------------------------------- #
# PDF fixtures -- built with PyMuPDF itself, entirely in-memory
# --------------------------------------------------------------------------- #
def _solid_image_bytes(width: int, height: int, color=(200, 50, 50)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


def _make_pdf(pages_images: list[list[tuple[int, int]]]) -> bytes:
    """Build a multi-page in-memory PDF. ``pages_images`` is one entry per
    page: a list of (width, height) image sizes to embed on that page (an
    empty list means a text-only page, no images)."""

    doc = fitz.open()
    for sizes in pages_images:
        page = doc.new_page(width=800, height=1000)
        if not sizes:
            page.insert_text((20, 20), "no images on this page")
        x = 20
        for w, h in sizes:
            img_bytes = _solid_image_bytes(w, h)
            page.insert_image(fitz.Rect(x, 20, x + w, 20 + h), stream=img_bytes)
            x += w + 20
    data = doc.tobytes()
    doc.close()
    return data


# --------------------------------------------------------------------------- #
# extract_largest_image -- real PyMuPDF calls, no mocking of fitz's API
# --------------------------------------------------------------------------- #
def test_extract_largest_image_picks_the_biggest_across_pages():
    pdf = _make_pdf([[(90, 90)], [], [(300, 200)]])
    img = figures.extract_largest_image(pdf)
    assert img is not None
    assert (img.width, img.height) == (300, 200)
    assert img.ext == "png"
    assert img.data  # actual embedded image bytes, not a placeholder


def test_extract_largest_image_filters_images_below_min_dimension():
    pdf = _make_pdf([[(20, 20)]])
    assert figures.extract_largest_image(pdf) is None


def test_extract_largest_image_ignores_tiny_image_when_a_real_one_exists():
    pdf = _make_pdf([[(20, 20), (150, 150)]])
    img = figures.extract_largest_image(pdf)
    assert img is not None
    assert (img.width, img.height) == (150, 150)


def test_extract_largest_image_respects_max_pages():
    pdf = _make_pdf([[(90, 90)], [], [(500, 500)]])
    img = figures.extract_largest_image(pdf, max_pages=2)
    assert img is not None
    assert (img.width, img.height) == (90, 90)  # the page-2 image is out of range


def test_extract_largest_image_returns_none_for_text_only_pdf():
    pdf = _make_pdf([[]])
    assert figures.extract_largest_image(pdf) is None


def test_extract_largest_image_returns_none_for_corrupt_bytes():
    assert figures.extract_largest_image(b"not a pdf at all, just garbage bytes") is None


def test_extract_largest_image_returns_none_for_empty_bytes():
    assert figures.extract_largest_image(b"") is None


# --------------------------------------------------------------------------- #
# _download_pdf
# --------------------------------------------------------------------------- #
def test_download_pdf_accepts_pdf_content_type():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 x")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    assert figures._download_pdf(client, "https://oa.example/x.pdf") == b"%PDF-1.4 x"


def test_download_pdf_accepts_pdf_magic_bytes_without_pdf_content_type():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"%PDF-1.4 x")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    assert figures._download_pdf(client, "https://oa.example/x.pdf") == b"%PDF-1.4 x"


def test_download_pdf_rejects_bot_walled_html_response():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>verify you're human</html>")

    client = httpx.Client(transport=httpx.MockTransport(routes))
    assert figures._download_pdf(client, "https://oa.example/x.pdf") is None


def test_download_pdf_returns_none_on_http_error():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(routes))
    assert figures._download_pdf(client, "https://oa.example/missing.pdf") is None


# --------------------------------------------------------------------------- #
# _upload_to_storage
# --------------------------------------------------------------------------- #
def test_upload_to_storage_puts_bytes_with_secret_key_auth_and_returns_public_url():
    seen = {}

    def routes(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = {k.lower(): v for k, v in request.headers.items()}
        seen["body"] = request.content
        return httpx.Response(200, json={"Key": "site-media/papers/x.png"})

    client = httpx.Client(transport=httpx.MockTransport(routes))
    url = figures._upload_to_storage(
        client, sb_url="https://proj.supabase.co", sb_key="secret-key",
        bucket="site-media", path="papers/person2023-x.png",
        data=b"pngbytes", content_type="image/png",
    )

    assert url == "https://proj.supabase.co/storage/v1/object/public/site-media/papers/person2023-x.png"
    assert seen["url"] == "https://proj.supabase.co/storage/v1/object/site-media/papers/person2023-x.png"
    assert seen["headers"]["apikey"] == "secret-key"
    assert seen["headers"]["authorization"] == "Bearer secret-key"
    assert seen["headers"]["x-upsert"] == "true"
    assert seen["headers"]["content-type"] == "image/png"
    assert seen["body"] == b"pngbytes"


def test_upload_to_storage_raises_figure_extraction_error_on_http_failure():
    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    client = httpx.Client(transport=httpx.MockTransport(routes))
    with pytest.raises(figures.FigureExtractionError):
        figures._upload_to_storage(
            client, sb_url="https://proj.supabase.co", sb_key="k",
            bucket="site-media", path="papers/x.png", data=b"x", content_type="image/png",
        )


def test_content_type_for_ext_known_and_unknown():
    assert figures._content_type_for_ext("png") == "image/png"
    assert figures._content_type_for_ext("JPEG") == "image/jpeg"
    assert figures._content_type_for_ext("weird") == "image/weird"


# --------------------------------------------------------------------------- #
# extract_figures -- the batch pipeline
# --------------------------------------------------------------------------- #
def test_extract_figures_scopes_query_to_project_linked_missing_image():
    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError("discover() should never be called -- there are no rows")

    sb = _FakeSB([])
    with _sources(routes) as sources:
        written = figures.extract_figures(sb, sources, sb_url="https://x", sb_key="k")

    assert written == 0
    assert sb.select_calls[0][2] == {"project_slug": "not.is.null", "image": "is.null"}


def test_extract_figures_no_rows_is_a_noop():
    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError("discover() should never be called -- there are no rows")

    sb = _FakeSB([])
    with _sources(routes) as sources:
        written = figures.extract_figures(sb, sources, sb_url="https://x", sb_key="k")

    assert written == 0
    assert sb.updates == []


def test_extract_figures_skips_row_that_already_has_image_defensive():
    """Belt-and-suspenders: even if a row with a non-null image somehow made
    it past the server-side filter, extract_figures must not touch it."""

    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError("discover() should never be called for a row that already has an image")

    sb = _FakeSB([_row(image="https://already.example/img.png")])
    with _sources(routes) as sources:
        written = figures.extract_figures(sb, sources, sb_url="https://x", sb_key="k")

    assert written == 0
    assert sb.updates == []


def test_extract_figures_skips_row_with_no_title_without_any_http_calls():
    sb = _FakeSB([_row(title="")])

    def routes(request: httpx.Request) -> httpx.Response:
        raise AssertionError("discover() should never be called for a titleless row")

    with _sources(routes) as sources:
        written = figures.extract_figures(sb, sources, sb_url="https://x", sb_key="k")

    assert written == 0
    assert sb.updates == []


def test_extract_figures_skips_when_no_oa_url_found():
    closed_work = dict(OPENALEX_WORK, open_access={"is_oa": False, "oa_status": "closed"})

    def routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=closed_work)

    sb = _FakeSB([_row()])
    with _sources(routes) as sources:
        written = figures.extract_figures(
            sb, sources, sb_url="https://x", sb_key="k", http_client=_no_calls_client(),
        )

    assert written == 0
    assert sb.updates == []


def test_extract_figures_skips_when_download_fails():
    def oa_routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OPENALEX_WORK)

    def http_routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    sb = _FakeSB([_row()])
    http = httpx.Client(transport=httpx.MockTransport(http_routes))
    with _sources(oa_routes) as sources:
        written = figures.extract_figures(
            sb, sources, sb_url="https://x", sb_key="k", http_client=http,
        )

    assert written == 0
    assert sb.updates == []


def test_extract_figures_writes_image_url_with_fill_if_empty_params():
    pdf_bytes = _make_pdf([[(300, 200)]])

    def oa_routes(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        return httpx.Response(200, json=OPENALEX_WORK)

    def http_routes(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == "https://oa.example/x.pdf"
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf_bytes)
        assert request.method == "PUT"
        assert str(request.url) == (
            "https://proj.supabase.co/storage/v1/object/site-media/papers/person2023-signal.png"
        )
        assert request.headers["authorization"] == "Bearer sekret"
        return httpx.Response(200, json={})

    sb = _FakeSB([_row()])
    http = httpx.Client(transport=httpx.MockTransport(http_routes))
    with _sources(oa_routes) as sources:
        written = figures.extract_figures(
            sb, sources, sb_url="https://proj.supabase.co", sb_key="sekret", http_client=http,
        )

    assert written == 1
    assert sb.updates == [(
        "publications",
        {"image": "https://proj.supabase.co/storage/v1/object/public/site-media/papers/person2023-signal.png"},
        {"slug": "eq.person2023-signal", "image": "is.null"},
    )]


def test_extract_figures_uses_search_path_when_link_is_not_a_doi_url():
    """A publisher/landing-page link must not be treated as a DOI (mirrors
    enrich.py's equivalent test -- figures.py duplicates the same helper)."""

    pdf_bytes = _make_pdf([[(300, 200)]])

    def oa_routes(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works"  # search, not /works/doi:<bogus>
        return httpx.Response(200, json={"results": [OPENALEX_WORK]})

    def http_routes(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf_bytes)
        return httpx.Response(200, json={})

    row = _row(link="https://publisher.example/x")
    sb = _FakeSB([row])
    http = httpx.Client(transport=httpx.MockTransport(http_routes))
    with _sources(oa_routes) as sources:
        written = figures.extract_figures(
            sb, sources, sb_url="https://proj.supabase.co", sb_key="k", http_client=http,
        )

    assert written == 1


def test_extract_figures_skips_corrupt_pdf_but_continues_batch():
    """A simulated corrupt-PDF failure for one paper must not crash the
    batch, and processing must continue to the next row."""

    good_pdf = _make_pdf([[(300, 200)]])

    def oa_routes(request: httpx.Request) -> httpx.Response:
        if "bad" in request.url.path:
            work = dict(
                OPENALEX_WORK,
                open_access={"is_oa": True, "oa_status": "gold", "oa_url": "https://oa.example/bad.pdf"},
            )
        else:
            work = dict(
                OPENALEX_WORK,
                open_access={"is_oa": True, "oa_status": "gold", "oa_url": "https://oa.example/good.pdf"},
            )
        return httpx.Response(200, json=work)

    def http_routes(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if str(request.url) == "https://oa.example/bad.pdf":
                # Looks like a PDF (content-type + magic bytes) but is not a
                # real, parseable document -- the "corrupt render" failure mode.
                return httpx.Response(
                    200, headers={"content-type": "application/pdf"}, content=b"%PDF-not-really-valid"
                )
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=good_pdf)
        return httpx.Response(200, json={})

    rows = [
        _row(slug="bad2023-x", link="https://doi.org/10.1111/bad.2023"),
        _row(slug="good2023-y", link="https://doi.org/10.1111/good.2023"),
    ]
    sb = _FakeSB(rows)
    http = httpx.Client(transport=httpx.MockTransport(http_routes))
    with _sources(oa_routes) as sources:
        written = figures.extract_figures(
            sb, sources, sb_url="https://proj.supabase.co", sb_key="k", http_client=http,
        )

    assert written == 1
    assert len(sb.updates) == 1
    assert sb.updates[0][2] == {"slug": "eq.good2023-y", "image": "is.null"}


def test_extract_figures_respects_limit():
    pdf_bytes = _make_pdf([[(300, 200)]])

    def oa_routes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OPENALEX_WORK)

    def http_routes(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf_bytes)
        return httpx.Response(200, json={})

    rows = [_row(slug=f"p{i}", link=f"https://doi.org/10.1111/x.202{i}") for i in range(3)]
    sb = _FakeSB(rows)
    http = httpx.Client(transport=httpx.MockTransport(http_routes))
    with _sources(oa_routes) as sources:
        written = figures.extract_figures(
            sb, sources, sb_url="https://x", sb_key="k", http_client=http, limit=1,
        )

    assert written == 1
