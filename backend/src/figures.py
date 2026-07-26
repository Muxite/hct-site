"""Best-effort figure extraction from open-access PDFs — free, no LLM involved.

``hct-manager extract-figures`` walks publications that are both project-linked
(``project_slug`` is set — the curated ~72-paper project-page subset, *not* the
full 551-paper archive) and still missing ``image``, resolves an open-access
PDF link the same way ``enrich.py`` does
(:meth:`~src.paper_sources.PaperSources.discover`), downloads the PDF, renders
the first few pages with PyMuPDF, picks the single largest embedded image, and
uploads it to the ``site-media`` Storage bucket at ``papers/<slug>.<ext>``.
``publications.image`` is then written with the same fill-if-empty discipline
as ``enrich.py``: the query that selects candidate rows already filters on
``image=is.null`` server-side, and the write itself is *also* a
``slug`` + ``image.is.null``-filtered PATCH — so this can never race with (or
clobber) an image an admin or an earlier run already set.

Every step here is best-effort and silent on failure: no OA link, a
failed/non-PDF download (bot-walled interstitial pages included), a corrupt or
password-protected PDF, or a page with no images at all above the noise floor
just means that paper is skipped — never raised — so one bad paper can't crash
the batch. The Storage upload is a plain ``httpx`` PUT against Supabase's
Storage REST endpoint using the secret key as the bearer token — same
secret-key-bypasses-RLS pattern the rest of this backend already relies on
(see ``db/schema.sql``'s ``site-media admin write`` policy, which only
constrains *authenticated* Storage writes, not the service/secret key).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import fitz  # PyMuPDF
import httpx

from src.paper_sources import PaperSources

# The only publications column this command ever writes, and only where it is
# currently null on that row — see extract_figures.
_IMAGE_FIELD = "image"

# Server-side scope: project-linked rows (the curated subset) missing an image.
# Both conditions are separate PostgREST query params, ANDed automatically —
# unlike enrich.py's _MISSING_FILTER this needs no 'or', just two filters.
_CANDIDATE_PARAMS = {"project_slug": "not.is.null", _IMAGE_FIELD: "is.null"}

# How many pages (from the start) to search for images. Figures worth using as
# a representative image are almost always on an early page; scanning the
# whole PDF would be slower for no real benefit.
DEFAULT_MAX_PAGES = 5

# Embedded images smaller than this on either side are treated as noise (logos,
# icons, tracking pixels) rather than a genuine figure, even if nothing bigger
# is on the page.
_MIN_DIMENSION = 80

_DEFAULT_BUCKET = "site-media"

# A publications.link that is itself a DOI redirect — mirrors enrich.py's
# _doi_from_link (duplicated rather than imported: the two modules are
# independent best-effort passes and this regex is a few lines).
_DOI_URL_RE = re.compile(r"^https?://(dx\.)?doi\.org/(?P<doi>10\.\S+)$", re.IGNORECASE)

# PyMuPDF's extract_image "ext" -> a Content-Type for the Storage upload.
# Falls back to a generic image/<ext> guess for anything not listed.
_CONTENT_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "jp2": "image/jp2",
    "jpx": "image/jp2",
}


class FigureExtractionError(RuntimeError):
    """Raised internally when a step fails; always caught before it can
    escape the batch loop (see extract_figures/_extract_for_publication)."""


@dataclass
class ExtractedImage:
    """One embedded image pulled out of a PDF, ready to upload."""

    data: bytes
    ext: str
    width: int
    height: int


def _doi_from_link(link: str | None) -> str | None:
    """The bare DOI if ``link`` is a doi.org redirect URL, else ``None``."""

    if not link:
        return None
    m = _DOI_URL_RE.match(link.strip())
    return m.group("doi") if m else None


def _content_type_for_ext(ext: str) -> str:
    return _CONTENT_TYPES.get(ext.lower(), f"image/{ext.lower()}" if ext else "application/octet-stream")


# --------------------------------------------------------------------------- #
# PDF fetch + render (pure-ish; httpx client and PyMuPDF are the only IO)
# --------------------------------------------------------------------------- #
def _download_pdf(client: httpx.Client, url: str) -> bytes | None:
    """GET ``url`` and return its bytes if the response actually looks like a
    PDF, else ``None``. Guards against bot-walled interstitial pages (HTML
    "please verify you're human" responses instead of the PDF) by checking
    both the Content-Type header and the ``%PDF`` magic bytes -- either is
    enough to trust it, but a response with neither is treated as unusable.
    """

    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    content_type = resp.headers.get("content-type", "")
    data = resp.content
    if "pdf" not in content_type.lower() and not data.startswith(b"%PDF"):
        return None
    return data or None


def extract_largest_image(pdf_bytes: bytes, *, max_pages: int = DEFAULT_MAX_PAGES) -> ExtractedImage | None:
    """The largest (by pixel area) embedded image across the first
    ``max_pages`` pages of a PDF, or ``None`` if the document won't open
    (corrupt/password-protected/not actually a PDF) or no image on those
    pages meets the minimum-size floor.

    Never raises: any PyMuPDF failure (a malformed document that opens but
    chokes on a specific page/image, in addition to the more common
    open-time failure) is treated the same as "no image found".
    """

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001 — corrupt/unsupported PDF is a normal skip case
        return None

    try:
        best: ExtractedImage | None = None
        for page_index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(page_index)
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:  # noqa: BLE001 — one bad xref shouldn't sink the page
                    continue
                width, height = info.get("width") or 0, info.get("height") or 0
                if width < _MIN_DIMENSION or height < _MIN_DIMENSION:
                    continue
                if best is None or (width * height) > (best.width * best.height):
                    best = ExtractedImage(
                        data=info["image"], ext=(info.get("ext") or "png"),
                        width=width, height=height,
                    )
        return best
    except Exception:  # noqa: BLE001 — malformed-but-openable PDF is still a skip, not a crash
        return None
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Storage upload (minimal — just enough to PUT bytes and hand back the URL)
# --------------------------------------------------------------------------- #
def _upload_to_storage(
    client: httpx.Client, *, sb_url: str, sb_key: str, bucket: str, path: str,
    data: bytes, content_type: str,
) -> str:
    """PUT ``data`` to ``{bucket}/{path}`` in Supabase Storage; return its
    public URL. Auth is the secret key as a bearer token — the same key
    ``SupabaseClient`` uses for PostgREST, which bypasses ``site-media``'s
    admin-write-only RLS the same way it bypasses table RLS everywhere else
    (this call never runs under an authenticated admin session). ``x-upsert``
    makes a re-run idempotent: if a previous run uploaded the object but a
    later step failed before the ``publications.image`` write landed, this
    overwrites rather than 409ing on the now-still-null row.
    """

    url = f"{sb_url.rstrip('/')}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    try:
        resp = client.put(url, headers=headers, content=data)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise FigureExtractionError(f"storage upload failed for {path}: {exc}") from exc
    return f"{sb_url.rstrip('/')}/storage/v1/object/public/{bucket}/{path}"


# --------------------------------------------------------------------------- #
# Per-publication + batch
# --------------------------------------------------------------------------- #
def _extract_for_publication(
    row: dict[str, Any],
    *,
    sources: PaperSources,
    http: httpx.Client,
    sb_url: str,
    sb_key: str,
    bucket: str,
    max_pages: int,
) -> str | None:
    """Best-effort: discover an OA PDF, extract its largest figure, upload it,
    and return the public Storage URL — or ``None`` if any step fails or finds
    nothing usable. Never raises; every failure just means "skip this paper".
    """

    slug = row.get("slug")
    title = (row.get("title") or "").strip()
    if not slug or not title:
        return None

    try:
        result = sources.discover(
            title=title,
            authors=row.get("authors") or None,
            year=row.get("year"),
            doi=_doi_from_link(row.get("link")),
        )
    except Exception:  # noqa: BLE001 — discovery is best-effort, matches enrich.py
        return None

    if not result.matched or not result.oa_url:
        return None

    pdf_bytes = _download_pdf(http, result.oa_url)
    if not pdf_bytes:
        return None

    image = extract_largest_image(pdf_bytes, max_pages=max_pages)
    if image is None:
        return None

    path = f"papers/{slug}.{image.ext}"
    try:
        return _upload_to_storage(
            http, sb_url=sb_url, sb_key=sb_key, bucket=bucket, path=path,
            data=image.data, content_type=_content_type_for_ext(image.ext),
        )
    except FigureExtractionError:
        return None


def extract_figures(
    supabase: Any,
    sources: PaperSources,
    *,
    sb_url: str,
    sb_key: str,
    http_client: httpx.Client | None = None,
    bucket: str = _DEFAULT_BUCKET,
    max_pages: int = DEFAULT_MAX_PAGES,
    limit: int | None = None,
) -> int:
    """Fill missing images across project-linked publications. Returns rows touched.

    Scoped, both ways, exactly like the rest of this codebase's fill-if-empty
    commands: the candidate query is filtered server-side to
    ``project_slug is not null AND image is null`` (never touches the full
    archive, never re-processes an already-illustrated paper), and the write
    itself repeats the ``image.is.null`` filter so it can't clobber a value an
    admin or an earlier run set in the meantime. ``limit`` caps how many
    publications get *written to* this run (matching ``enrich``/``describe``'s
    convention), not how many are scanned.

    Every per-paper failure — no OA link, a blocked/non-PDF download, a
    corrupt render, no image found, an upload error — is caught inside
    :func:`_extract_for_publication`; the ``except Exception`` around that
    call below is a second line of defense so nothing here can ever raise out
    of the loop and abort the batch.
    """

    http = http_client or httpx.Client(timeout=60.0, follow_redirects=True)
    owns_client = http_client is None
    try:
        rows = supabase.select(
            "publications",
            columns="slug,title,authors,year,link,project_slug,image",
            params=dict(_CANDIDATE_PARAMS),
        )
        written = 0
        for row in rows:
            if limit is not None and written >= limit:
                break
            if row.get(_IMAGE_FIELD):
                continue  # defensive: server-side filter should already exclude this

            try:
                url = _extract_for_publication(
                    row, sources=sources, http=http, sb_url=sb_url, sb_key=sb_key,
                    bucket=bucket, max_pages=max_pages,
                )
            except Exception:  # noqa: BLE001 — one paper's bug must not sink the batch
                url = None

            if not url:
                continue
            supabase.update(
                "publications",
                {_IMAGE_FIELD: url},
                params={"slug": f"eq.{row['slug']}", _IMAGE_FIELD: "is.null"},
            )
            written += 1
        return written
    finally:
        if owns_client:
            http.close()
