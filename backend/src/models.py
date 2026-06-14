"""Pydantic schema for publication data — the contract written to YAML.

These models are the single source of truth for what a publication looks like.
The LLM extraction layer is asked to emit JSON matching :class:`PublicationSet`;
anything that fails validation here is rejected before it can reach the YAML the
frontend renders. Keep everything YAML/JSON-friendly (plain str/int/list/dict)
so ``model_dump(mode="json")`` round-trips through ``yaml.safe_dump`` cleanly.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Year sanity bounds. Lower bound predates any plausible record; upper bound
# leaves headroom for "in press" / next-year entries without being open-ended.
_MIN_YEAR = 1900
_MAX_YEAR = 2100


class PubType(str, Enum):
    """Coarse publication type. Mirrors common BibTeX entry kinds."""

    article = "article"
    inproceedings = "inproceedings"
    preprint = "preprint"
    book = "book"
    incollection = "incollection"
    thesis = "thesis"
    techreport = "techreport"
    misc = "misc"


def slug_for(authors: list[str], year: int, title: str) -> str:
    """Build a stable, human-readable id: ``<firstauthorlast><year>-<title>``.

    Deterministic so re-scraping the same paper yields the same id (dedupe key).
    Example: ``(["Hongzhi Zhu", ...], 2022, "A unified representation ...")``
    -> ``"zhu2022-a-unified-representation-of-control-logic"``.
    """

    last = authors[0].split()[-1] if authors and authors[0].split() else "anon"
    last = _slugify(last).replace("-", "")
    title_part = "-".join(_slugify(title).split("-")[:7])  # cap length
    return f"{last}{year}-{title_part}".strip("-")


# Curly/typographic punctuation -> ASCII, applied before slugifying. NFKD does
# NOT decompose these, so "It's" and "It’s" used to produce different slugs and
# the same paper got two rows (dedupe is by slug).
_PUNCT_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _slugify(text: str) -> str:
    """Lowercase ASCII kebab-case. Drops accents and non-alphanumerics."""

    text = text.translate(_PUNCT_MAP)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower())
    return text.strip("-")


class Publication(BaseModel):
    """One paper. Overview fields are always present; ``description`` is optional."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable slug, used as the dedupe key.")
    title: str
    authors: list[str] = Field(..., min_length=1)
    year: int = Field(..., ge=_MIN_YEAR, le=_MAX_YEAR)
    type: PubType = PubType.misc
    venue: str | None = None
    link: str | None = Field(default=None, description="DOI or canonical URL.")
    bibtex: str | None = None
    description: str | None = Field(
        default=None, description="Optional longer, lab-style writeup."
    )

    @field_validator("id", "title")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()

    @field_validator("authors", mode="before")
    @classmethod
    def _coerce_authors(cls, v):
        # LLMs sometimes emit the author list as a single delimited string
        # ("N Ashjaee, J Street, S Fels"); split it back into a list. An empty
        # list/string still fails the cleaning check below (-> repair), so the
        # "at least one author" contract is preserved.
        if isinstance(v, str):
            parts = re.split(r"\s*(?:;| and |,)\s*", v)
            return [p.strip() for p in parts if p.strip()]
        return v

    @field_validator("authors")
    @classmethod
    def _authors_clean(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip() for a in v if a and a.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty author is required")
        return cleaned

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v):
        # Map free-text the LLM may emit ("Journal Article", "Conference paper",
        # "arXiv preprint") onto the closest BibTeX-ish bucket; default misc.
        if v is None or v == "":
            return PubType.misc
        if not isinstance(v, str):
            return v
        s = v.strip().lower()
        try:
            return PubType(s)
        except ValueError:
            pass
        for needle, t in (
            ("proceed", PubType.inproceedings), ("conf", PubType.inproceedings),
            ("arxiv", PubType.preprint), ("preprint", PubType.preprint),
            ("journal", PubType.article), ("article", PubType.article),
            ("chapter", PubType.incollection), ("book", PubType.book),
            ("thesis", PubType.thesis), ("dissert", PubType.thesis),
            ("tech", PubType.techreport), ("report", PubType.techreport),
        ):
            if needle in s:
                return t
        return PubType.misc

    @field_validator("link")
    @classmethod
    def _link_is_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("link must start with http:// or https://")
        return v


class PublicationSet(BaseModel):
    """The whole publications document written to ``publications.yaml``."""

    model_config = ConfigDict(extra="ignore")

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    publications: list[Publication] = Field(default_factory=list)

    def by_year(self) -> dict[int, list[Publication]]:
        """Group publications by year, newest year first (render convenience)."""

        out: dict[int, list[Publication]] = {}
        for pub in self.publications:
            out.setdefault(pub.year, []).append(pub)
        return {y: out[y] for y in sorted(out, reverse=True)}

    def deduped(self) -> "PublicationSet":
        """Return a copy with duplicate ids collapsed (first occurrence wins)."""

        seen: dict[str, Publication] = {}
        for pub in self.publications:
            seen.setdefault(pub.id, pub)
        return self.model_copy(update={"publications": list(seen.values())})


def publication_row(pub: Publication) -> dict:
    """Map a :class:`Publication` to a ``publications`` table row.

    The model's ``id`` is our stable slug; in the DB that lives in ``slug`` while
    ``id`` is a server-generated uuid, so we don't send ``id``.
    """

    return {
        "slug": pub.id,
        "title": pub.title,
        "authors": list(pub.authors),
        "year": pub.year,
        "type": pub.type.value,
        "venue": pub.venue,
        "link": pub.link,
        "bibtex": pub.bibtex,
        "description": pub.description,
    }


class TimelineEntry(BaseModel):
    """One entry in the "Latest" timeline (the 5 most recent publications)."""

    model_config = ConfigDict(extra="ignore")

    slug: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    date_label: str | None = None
    blurb: str | None = None
    position: int = 0

    def row(self) -> dict:
        return self.model_dump(mode="json")


class Person(BaseModel):
    """A lab member (synced from ``people.yaml``)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    role: str | None = None
    email: str | None = None
    photo: str | None = None
    bio: str | None = None
    kind: str = "current"
    sort_order: int = 0

    def row(self) -> dict:
        return self.model_dump(mode="json")


class ResearchProject(BaseModel):
    """A research area/project (synced from ``research.yaml``)."""

    model_config = ConfigDict(extra="ignore")

    title: str
    tagline: str | None = None
    description: str | None = None
    link: str | None = None
    image: str | None = None
    kind: str = "current"  # 'current' | 'archived'
    sort_order: int = 0

    def row(self) -> dict:
        return self.model_dump(mode="json")


class SiteContent(BaseModel):
    """A key/value blurb for a free-text site section."""

    model_config = ConfigDict(extra="ignore")

    key: str
    value: dict = Field(default_factory=dict)

    def row(self) -> dict:
        return {"key": self.key, "value": self.value}
