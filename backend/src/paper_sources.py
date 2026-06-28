"""Find and validate a canonical link (and a free full-text link) for a paper.

Given a paper's bibliographic facts (title, authors, year, optional DOI), we look
it up in keyless academic APIs and return the best *validated* link plus the
abstract, so the summary step has real grounding text. Two sources, both injected
``httpx.Client``-friendly (MockTransport in tests):

* **OpenAlex** (primary) — one call returns the canonical landing page, an open
  access URL when one exists, and the abstract (as an inverted index we
  reconstruct). Very generous, keyless, "polite pool" via ``mailto``.
* **Crossref** (fallback) — DOI metadata + sometimes a JATS abstract.

We deliberately **never** touch scholar.google.* (it CAPTCHA-blocks the runner and
is on a hard HOLD). arXiv preprints surface through OpenAlex locations, so there is
no separate arXiv path.

Validation is conservative, in the spirit of ``cv_parse``: a candidate is only
accepted when its title closely matches and the year is within a year. A wrong
link attached silently is worse than no link, so a weak match is rejected (the
caller can still inspect ``LinkResult.record`` and ``reason``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import httpx

# Below this normalized-title similarity we refuse to attach a discovered link.
DEFAULT_MATCH_THRESHOLD = 0.72
# Years from CVs vs. the publisher's "online first" date often differ by one.
DEFAULT_YEAR_TOLERANCE = 1

DEFAULT_OPENALEX_BASE = "https://api.openalex.org"
DEFAULT_CROSSREF_BASE = "https://api.crossref.org"
DEFAULT_EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
DEFAULT_NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# Below this, a "full text" response is treated as an error stub, not a body.
_MIN_FULLTEXT = 500


class PaperSourceError(RuntimeError):
    """Raised when an academic-API call fails outright."""


@dataclass
class WorkRecord:
    """Normalized view of one work from an academic API."""

    source: str  # "openalex" | "crossref"
    title: str
    doi: str | None = None
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    landing_url: str | None = None  # canonical publisher landing page
    oa_url: str | None = None  # free full text (pdf or OA landing), if any
    abstract: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_url(self) -> str | None:
        """Best stable link to the article: the DOI when we have one, else the
        landing page. DOIs are preferred because they survive publisher migrations."""

        if self.doi:
            return f"https://doi.org/{self.doi}"
        return self.landing_url


@dataclass
class LinkResult:
    """Outcome of discovering a link for one paper."""

    canonical_url: str | None
    oa_url: str | None
    abstract: str | None
    confidence: float
    matched: bool
    reason: str
    record: WorkRecord | None = None


# --------------------------------------------------------------------------- #
# Text helpers (pure)
# --------------------------------------------------------------------------- #
_WS = re.compile(r"\s+")
_NONWORD = re.compile(r"[^a-z0-9 ]+")
_TAG = re.compile(r"<[^>]+>")


def normalize_title(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy matching."""

    s = (s or "").lower()
    s = _NONWORD.sub(" ", s)
    return _WS.sub(" ", s).strip()


def title_similarity(a: str, b: str) -> float:
    """0..1 similarity of two titles, robust to punctuation/word-order noise.

    Combines a character-level ratio (SequenceMatcher) with a token Jaccard so
    that reordered or partially-truncated titles still score well; takes the
    larger of the two.
    """

    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(ratio, jaccard)


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Rebuild plain text from OpenAlex's ``abstract_inverted_index``.

    The index maps each word to the positions it occupies; we place words back
    at their positions and join. Returns None for an empty/missing index.
    """

    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions).strip() or None


def strip_jats(abstract: str | None) -> str | None:
    """Crossref abstracts are JATS XML (``<jats:p>...``); strip tags to text."""

    if not abstract:
        return None
    text = _TAG.sub(" ", abstract)
    text = _WS.sub(" ", text).strip()
    return text or None


def _doi_only(doi: str | None) -> str | None:
    """Reduce any DOI form (URL, doi: prefix) to the bare ``10.x/...`` id, lowercased."""

    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:", "", doi)
    return doi or None


# --------------------------------------------------------------------------- #
# Record parsing (pure, per source)
# --------------------------------------------------------------------------- #
def parse_openalex_work(w: dict[str, Any]) -> WorkRecord:
    """Map an OpenAlex Work object onto a :class:`WorkRecord`."""

    authors = [
        (a.get("author") or {}).get("display_name", "").strip()
        for a in (w.get("authorships") or [])
    ]
    authors = [a for a in authors if a]
    primary = w.get("primary_location") or {}
    best_oa = w.get("best_oa_location") or {}
    oa = w.get("open_access") or {}
    venue = (primary.get("source") or {}).get("display_name")
    oa_url = oa.get("oa_url") or best_oa.get("pdf_url") or best_oa.get("landing_page_url")
    return WorkRecord(
        source="openalex",
        title=(w.get("title") or w.get("display_name") or "").strip(),
        doi=_doi_only(w.get("doi")),
        year=w.get("publication_year"),
        authors=authors,
        venue=venue,
        landing_url=primary.get("landing_page_url"),
        oa_url=oa_url,
        abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
        raw=w,
    )


def parse_crossref_work(m: dict[str, Any]) -> WorkRecord:
    """Map a Crossref ``message`` (item) onto a :class:`WorkRecord`."""

    title_list = m.get("title") or []
    title = (title_list[0] if title_list else "").strip()
    authors = []
    for a in m.get("author") or []:
        name = " ".join(p for p in [a.get("given"), a.get("family")] if p).strip()
        if name:
            authors.append(name)
    year = None
    parts = ((m.get("issued") or {}).get("date-parts") or [[None]])[0]
    if parts and parts[0]:
        year = int(parts[0])
    container = m.get("container-title") or []
    # A full-text link Crossref knows about (often the publisher PDF).
    oa_url = None
    for link in m.get("link") or []:
        if link.get("URL"):
            oa_url = link["URL"]
            break
    return WorkRecord(
        source="crossref",
        title=title,
        doi=_doi_only(m.get("DOI")),
        year=year,
        authors=authors,
        venue=(container[0] if container else None),
        landing_url=m.get("URL"),
        oa_url=oa_url,
        abstract=strip_jats(m.get("abstract")),
        raw=m,
    )


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class PaperSources:
    """Look up papers in OpenAlex (primary) and Crossref (fallback)."""

    def __init__(
        self,
        *,
        contact_email: str = "",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        openalex_base: str = DEFAULT_OPENALEX_BASE,
        crossref_base: str = DEFAULT_CROSSREF_BASE,
        europepmc_base: str = DEFAULT_EUROPEPMC_BASE,
        ncbi_eutils: str = DEFAULT_NCBI_EUTILS,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        year_tolerance: int = DEFAULT_YEAR_TOLERANCE,
    ) -> None:
        self._email = contact_email.strip()
        self._oa = openalex_base.rstrip("/")
        self._cr = crossref_base.rstrip("/")
        self._epmc = europepmc_base.rstrip("/")
        self._eutils = ncbi_eutils.rstrip("/")
        self._threshold = match_threshold
        self._year_tol = year_tolerance
        self._client = client or httpx.Client(timeout=timeout)

    def _params(self, extra: dict[str, str]) -> dict[str, str]:
        p = dict(extra)
        if self._email:
            p["mailto"] = self._email  # polite pool for both APIs
        return p

    def _get(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            resp = self._client.get(url, params=self._params(params))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise PaperSourceError(f"GET {url} failed: {exc}") from exc

    # -- OpenAlex ---------------------------------------------------------- #
    def openalex_by_doi(self, doi: str) -> WorkRecord | None:
        bare = _doi_only(doi)
        if not bare:
            return None
        try:
            data = self._get(f"{self._oa}/works/doi:{bare}", {})
        except PaperSourceError:
            return None
        return parse_openalex_work(data) if data else None

    def openalex_search(self, title: str, year: int | None = None, *, per_page: int = 5) -> list[WorkRecord]:
        filt = f"title.search:{title}"
        if year:
            filt += f",publication_year:{year}"
        try:
            data = self._get(self._oa + "/works", {"filter": filt, "per_page": str(per_page)})
        except PaperSourceError:
            return []
        return [parse_openalex_work(w) for w in (data.get("results") or [])]

    # -- Crossref ---------------------------------------------------------- #
    def crossref_by_doi(self, doi: str) -> WorkRecord | None:
        bare = _doi_only(doi)
        if not bare:
            return None
        try:
            data = self._get(f"{self._cr}/works/{bare}", {})
        except PaperSourceError:
            return None
        msg = data.get("message") if data else None
        return parse_crossref_work(msg) if msg else None

    def crossref_search(self, title: str, year: int | None = None, *, rows: int = 5) -> list[WorkRecord]:
        try:
            data = self._get(
                self._cr + "/works",
                {"query.bibliographic": title, "rows": str(rows)},
            )
        except PaperSourceError:
            return []
        items = ((data.get("message") or {}).get("items")) or []
        return [parse_crossref_work(m) for m in items]

    # -- Open-access full text (PMC) --------------------------------------- #
    def pmcid_for(self, doi: str) -> str | None:
        """Resolve a DOI to a PubMed Central id via Europe PMC (or None)."""

        bare = _doi_only(doi)
        if not bare:
            return None
        try:
            data = self._get(
                self._epmc + "/search",
                {"query": f"DOI:{bare}", "format": "json", "resultType": "core"},
            )
        except PaperSourceError:
            return None
        results = (data.get("resultList") or {}).get("result") or []
        return results[0].get("pmcid") if results else None

    def pmc_fulltext(self, pmcid: str | None) -> str | None:
        """Fetch open-access full text for a PMC id via NCBI efetch (JATS -> text).

        NCBI serves OA articles' full text as XML even when Europe PMC's own XML
        endpoint 404s for very recent papers. Returns plain text, or None if the
        article is not open-access full text (NCBI returns a short error stub).
        """

        if not pmcid:
            return None
        num = pmcid[3:] if pmcid.upper().startswith("PMC") else pmcid
        params = {"db": "pmc", "id": num, "rettype": "xml", "tool": "hct-manager"}
        if self._email:
            params["email"] = self._email
        try:
            resp = self._client.get(self._eutils + "/efetch.fcgi", params=params)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        text = strip_jats(resp.text)
        return text if text and len(text) >= _MIN_FULLTEXT else None

    def fulltext_by_doi(self, doi: str) -> str | None:
        """Best-effort open-access full text for a DOI (PMC). Empty -> None."""

        return self.pmc_fulltext(self.pmcid_for(doi))

    # -- High level -------------------------------------------------------- #
    def _best_match(self, candidates: list[WorkRecord], title: str) -> tuple[WorkRecord | None, float]:
        best, best_score = None, 0.0
        for rec in candidates:
            score = title_similarity(title, rec.title)
            if score > best_score:
                best, best_score = rec, score
        return best, best_score

    def _year_ok(self, want: int | None, got: int | None) -> bool:
        if want is None or got is None:
            return True
        return abs(want - got) <= self._year_tol

    def discover(
        self,
        *,
        title: str,
        authors: list[str] | None = None,
        year: int | None = None,
        doi: str | None = None,
    ) -> LinkResult:
        """Find + validate a link for one paper.

        If a DOI is already known we trust it as canonical (CVs are authoritative)
        and only use the API record to enrich it with an OA URL + abstract. With no
        DOI we search and require a confident title match before attaching anything.
        """

        # Known DOI: trust it, enrich from whichever source answers.
        if _doi_only(doi):
            rec = self.openalex_by_doi(doi) or self.crossref_by_doi(doi)
            conf = title_similarity(title, rec.title) if rec else 1.0
            canonical = f"https://doi.org/{_doi_only(doi)}"
            return LinkResult(
                canonical_url=canonical,
                oa_url=rec.oa_url if rec else None,
                abstract=rec.abstract if rec else None,
                confidence=conf,
                matched=True,
                reason="known DOI (trusted)" + ("" if rec else "; no API record found"),
                record=rec,
            )

        # No DOI: search OpenAlex, then Crossref, take the best title match.
        candidates = self.openalex_search(title, year)
        rec, score = self._best_match(candidates, title)
        if not rec or score < self._threshold or not self._year_ok(year, rec.year):
            cr = self.crossref_search(title, year)
            rec2, score2 = self._best_match(cr, title)
            if rec2 and score2 > score:
                rec, score = rec2, score2

        if rec is None:
            return LinkResult(None, None, None, 0.0, False, "no candidates found", None)

        matched = score >= self._threshold and self._year_ok(year, rec.year)
        reason = (
            f"title match {score:.2f}"
            + ("" if self._year_ok(year, rec.year) else f"; year {year} vs {rec.year} off")
            + ("" if matched else f" < threshold {self._threshold:.2f} (rejected)")
        )
        return LinkResult(
            canonical_url=rec.canonical_url if matched else None,
            oa_url=rec.oa_url if matched else None,
            abstract=rec.abstract if matched else None,
            confidence=score,
            matched=matched,
            reason=reason,
            record=rec,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PaperSources":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
