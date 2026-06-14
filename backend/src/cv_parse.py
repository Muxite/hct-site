"""Deterministic CV publication parsing — the primary extraction path.

The lab CV is the primary publication source and its structure is stable (the
UBC faculty form: numbered ALL-CAPS sections, lettered subsections, ~one entry
per paragraph). So before any LLM is involved, this module splits the
publications section into individual entries and parses each one with plain
heuristics into a validated :class:`~src.models.Publication`.

The heuristics are deliberately *conservative*: an entry that looks ambiguous
(no year, no plausible author run, dangling title) fails fast with the fields
that couldn't be filled, and only that single entry is handed to the LLM
fallback (see ``src/cv.py``). Every attempt produces a :class:`ParseOutcome`
so the run can report exactly how often deterministic parsing fails, in which
CV section, and on which fields — the feedback loop for improving the
heuristics over time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from pydantic import ValidationError

from src.models import Publication, PubType, slug_for

# --------------------------------------------------------------------------- #
# Sections


class CVSection(str, Enum):
    """Coarse CV subsection an entry was found under (drives ``PubType``)."""

    journal = "journal"
    conference = "conference"
    book_chapter = "book_chapter"
    book = "book"
    patent = "patent"
    thesis = "thesis"
    other = "other"
    unknown = "unknown"

    @property
    def pub_type(self) -> PubType:
        return _SECTION_TYPE[self]


_SECTION_TYPE = {
    CVSection.journal: PubType.article,
    CVSection.conference: PubType.inproceedings,
    CVSection.book_chapter: PubType.incollection,
    CVSection.book: PubType.book,
    CVSection.patent: PubType.misc,
    CVSection.thesis: PubType.thesis,
    CVSection.other: PubType.misc,
    CVSection.unknown: PubType.misc,
}

# UBC CV form headings: "1.REFEREED PUBLICATIONS" / "(a)Journal".
_TOP_HEADER = re.compile(r"^\s*\d+\.\s*[A-Z][A-Z\s,&/()'-]+$")
_SUB_HEADER = re.compile(r"^\s*\(([a-z])\)\s*(.+?)\s*$")


def classify_section(top: str, sub: str) -> CVSection:
    """Map heading text (top section + lettered subsection) to a CVSection."""

    s = sub.lower()
    if s:
        if "journal" in s:
            return CVSection.journal
        if "chapter" in s:
            return CVSection.book_chapter
        if "conference" in s or "workshop" in s or "proceeding" in s:
            return CVSection.conference
        if "authored" in s or "edited" in s:
            return CVSection.book
    t = top.lower()
    if "book" in t:
        return CVSection.book
    if "patent" in t:
        return CVSection.patent
    if "thes" in t or "dissert" in t:
        return CVSection.thesis
    if "copyright" in t or "artistic" in t or "other" in t:
        return CVSection.other
    return CVSection.unknown


# --------------------------------------------------------------------------- #
# Data shapes


@dataclass
class CVEntry:
    """One publication entry as found in the CV (1+ source paragraphs)."""

    text: str
    section: CVSection
    raw_lines: list[str] = field(default_factory=list)
    line_no: int = 0


@dataclass
class ParseOutcome:
    """The result of one entry's trip through the parsing pipeline."""

    path: str  # "deterministic" | "llm" | "failed"
    section: str
    slug: str | None = None
    failed_fields: list[str] = field(default_factory=list)
    entry_preview: str = ""
    error: str | None = None


def _preview(text: str, n: int = 120) -> str:
    return re.sub(r"\s+", " ", text).strip()[:n]


# --------------------------------------------------------------------------- #
# Entry splitting

# A line that *starts* a new entry begins with an author run. Covers the
# styles seen in real CVs: "Ashjaee, N.", "N. Ashjaee", "Hajipour M,",
# "Victor Zappi," — but not prose ("Conceptual framework for ...").
_ENTRY_START = re.compile(
    r"""^(?:
        [A-ZÀ-Þ][\w'’\-À-ž]+\.?[,;]\s           # Surname, (also "Tran.," / "Malakoutian;")
      | [A-Z]\.\s*[A-Z]                          # N. Ashjaee / H.Zhu
      | [A-ZÀ-Þ][\w'’\-À-ž]+\.?\s+[A-Z]{1,3}\.?[,\s]  # Hajipour M, / Fels. S.
      | [A-ZÀ-Þ][\w'’\-À-ž]+\s+[A-ZÀ-Þ][\w'’.\-À-ž]+  # Victor Zappi
    )""",
    re.VERBOSE,
)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _normalize(text: str) -> str:
    """NBSP -> space, collapse whitespace, drop entry markers.

    ``*`` flags primary-importance entries and ``†``/``‡`` flag student
    authors in the UBC form — both are noise for parsing and block the
    entry-start patterns when they prefix a name.
    """

    text = text.replace("\xa0", " ").replace("†", "").replace("‡", "")
    text = re.sub(r"^\s*\*\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_entries(section_text: str) -> list[CVEntry]:
    """Group section lines into publication entries, tracking headings.

    The docx reader emits one line per paragraph; most entries are a single
    line, but some wrap across several (authors on their own lines, the
    title/venue/year on a later one). A new entry starts at an author-looking
    line — but only once the current entry already carries a year (i.e. looks
    complete); year-less lines are continuations. Preamble before the first
    heading (the UBC form's name/date block) is skipped.
    """

    lines = section_text.splitlines()
    has_headers = any(_TOP_HEADER.match(l) or _SUB_HEADER.match(l) for l in lines)

    entries: list[CVEntry] = []
    buf: list[str] = []
    buf_start = 0
    top, sub = "", ""
    seen_header = not has_headers

    def flush() -> None:
        nonlocal buf
        if buf:
            text = _normalize(" ".join(buf))
            if text:
                entries.append(
                    CVEntry(
                        text=text,
                        section=classify_section(top, sub),
                        raw_lines=list(buf),
                        line_no=buf_start,
                    )
                )
        buf = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _TOP_HEADER.match(stripped):
            flush()
            top, sub = stripped, ""
            seen_header = True
            continue
        m = _SUB_HEADER.match(stripped)
        if m:
            flush()
            sub = m.group(2)
            seen_header = True
            continue
        if not seen_header:
            continue  # UBC form preamble (name/date/asterisk note)
        clean = _normalize(stripped)
        starts = bool(_ENTRY_START.match(clean))
        complete = bool(buf) and bool(_YEAR.search(" ".join(buf)))
        if starts and (not buf or complete):
            flush()
            buf_start = i
        buf.append(stripped)
    flush()
    return entries


# --------------------------------------------------------------------------- #
# Per-entry field heuristics

_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_DOI_ORG = re.compile(r"\bdoi\.org/(\S+)", re.IGNORECASE)
_BARE_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)")
_PAREN_YEAR = re.compile(r"\(\s*((?:19|20)\d{2})\s*\)\s*[.:]?")
# ACM-style bare year sentence: "..., and Kyoungwon Seo. 2025. Title. In ..."
_DOT_YEAR = re.compile(r"\.\s*((?:19|20)\d{2})\s*[.:]\s+")
# Sentence boundary inside a title segment (the venue follows in compact style).
_SENTENCE = re.compile(r"\.\s+(?=[A-Z])")

# Name-token shapes. Initials: "M", "JB", "N.", "TD.", "J.J.".
_INITIALS = re.compile(r"^(?:[A-Z]{1,4}\.?|(?:[A-Z]\.){1,3}[A-Z]?\.?)$")
_NAME_WORD = re.compile(r"^[A-ZÀ-Þ][\w'’\-À-ž]*\.?$")
_PARTICLES = {
    "de", "da", "dos", "das", "del", "der", "den", "van", "von", "la", "le",
    "el", "al", "bin", "ter", "di", "du", "ten",
}

# Words a real title never dangles on (a cut-off at a comma mid-title).
_DANGLING = {
    "a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with", "vs",
}

# A tail segment that ends the venue (volume/pages/dates/identifiers).
_TAIL_STOP = re.compile(
    r"""(?:
        ^\d | ^[Vv]ol | ^[Nn]o\.? \s | ^pp | ^\d*\s*pages? | ^[Aa]rt\.
      | ^DOI | ^doi | ^http | ^accepted | ^to\s+appear | ^[Ii]n\s+[Pp]ress
      | ^Article\s+\d
      | ^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)
      | \b(?:19|20)\d{2}\b
    )""",
    re.VERBOSE,
)


def _is_name_token(word: str) -> bool:
    return bool(
        _INITIALS.match(word)
        or _NAME_WORD.match(word)
        or word.lower() in _PARTICLES
    )


def _name_like(seg: str) -> bool:
    """Does a comma-segment look like (part of) an author name run?"""

    words = seg.split()
    if not words or len(words) > 5:
        return False
    return all(w in ("and", "&") or _is_name_token(w) for w in words)


def _parse_authors(segs: list[str]) -> list[str]:
    """Reassemble author names from comma-segments, normalising to
    "Given Surname" order so the slug's first-author surname is stable.

    Handles the styles that actually occur: "Surname, I." pairs (also the
    sloppy "Ashjaee, N. Street, J." variant where an initial and the next
    surname share a segment), "Surname II" (initials attached), and full
    names. Imperfect middle authors are acceptable; the first author drives
    the dedupe slug.
    """

    parts: list[str] = []
    for seg in segs:
        for p in re.split(r"\s+(?:and|&)\s+|^(?:and|&)\s+", seg):
            p = (p or "").strip(" .;")
            if p:
                parts.append(p)

    authors: list[str] = []
    pending: str | None = None  # a bare surname waiting for its given/initials
    for p in parts:
        words = p.split()
        if len(words) == 1:
            w = words[0]
            if pending:
                authors.append(f"{w} {pending}")
                pending = None
            elif _INITIALS.match(w) and len(w.rstrip(".")) <= 3:
                continue  # orphan initials — nothing to attach them to
            else:
                pending = w
        elif _INITIALS.match(words[0]):
            if pending:
                # "Ashjaee, N. Street" — the initial closes the pending
                # surname; the remainder starts the next author.
                authors.append(f"{words[0]} {pending}")
                pending = None
                rest = words[1:]
                if len(rest) == 1 and not _INITIALS.match(rest[0]):
                    pending = rest[0]
                elif rest:
                    authors.append(" ".join(rest))
            else:
                authors.append(p)  # "N. Street", "C. Antonio Sánchez"
        else:
            if pending:
                authors.append(pending)
                pending = None
            # "Hajipour M" -> "M Hajipour"; "Pai S A" -> "S A Pai"
            i = len(words)
            while i > 1 and _INITIALS.match(words[i - 1]):
                i -= 1
            if i < len(words):
                authors.append(f"{' '.join(words[i:])} {' '.join(words[:i])}")
            else:
                authors.append(p)  # "Victor Zappi", "Ortiz La Banca"
    if pending:
        authors.append(pending)
    return authors


def _extract_link(text: str) -> str | None:
    m = _URL.search(text)
    if m:
        return m.group(0).rstrip(".,;)")
    m = _DOI_ORG.search(text)
    if m:
        return "https://doi.org/" + m.group(1).rstrip(".,;)")
    m = _BARE_DOI.search(text)
    if m:
        return "https://doi.org/" + m.group(1).rstrip(".,;)")
    return None


def _extract_year(text: str) -> int | None:
    m = _PAREN_YEAR.search(text)
    if m:
        return int(m.group(1))
    # Strip links/DOIs first — they embed year-like digit runs.
    stripped = _BARE_DOI.sub(" ", _URL.sub(" ", text))
    years = _YEAR.findall(stripped)
    return int(years[-1]) if years else None


def parse_entry(entry: CVEntry) -> tuple[Publication | None, list[str]]:
    """Deterministically parse one entry. Returns ``(publication, [])`` on
    success or ``(None, failed_fields)`` when the heuristics can't fill the
    schema confidently (those fields name what was missing/ambiguous)."""

    text = _normalize(entry.text)
    link = _extract_link(text)
    year = _extract_year(text)

    failed: list[str] = []
    if year is None:
        failed.append("year")

    # Walk comma/semicolon segments: author run -> title -> venue tail.
    body = _BARE_DOI.sub(" ", _URL.sub(" ", text))
    segments = [s.strip() for s in re.split(r"[,;]", body) if s.strip()]
    author_segs: list[str] = []
    title_parts: list[str] = []
    tail: list[str] = []
    state = "authors"
    for seg in segments:
        if state == "authors":
            m = _PAREN_YEAR.search(seg) or _DOT_YEAR.search(seg)
            if m:
                pre = seg[: m.start()].strip(" .")
                post = seg[m.end():].strip()
                if pre and _name_like(pre):
                    author_segs.append(pre)
                elif pre:
                    title_parts.append(pre)
                if post:
                    title_parts.append(post)
                state = "tail" if title_parts else "title"
                continue
            if _name_like(seg):
                author_segs.append(seg)
                continue
            # The last author and the title can share a segment in compact
            # style ("Oxland TR. Estimation ...", "and R. Abugharbieh. A...").
            # Peel off the longest sentence-prefix that still reads as names.
            seg = re.sub(r"^(?:and|&)\s+", "", seg)
            best_end = None
            for sm in _SENTENCE.finditer(seg):
                if _name_like(seg[: sm.start()]):
                    best_end = sm
                else:
                    break
            if best_end is not None:
                author_segs.append(seg[: best_end.start()])
                seg = seg[best_end.end():]
            title_parts.append(seg)
            state = "title"
            continue
        if state == "title":
            if not title_parts:
                title_parts.append(seg)
                continue
            if seg[0].islower() and not _TAIL_STOP.search(seg):
                title_parts.append(seg)  # title continued across a comma
                continue
            state = "tail"
        tail.append(seg)

    if title_parts:
        # Compact style runs title and venue together in one comma-less
        # sentence ("...Performance in Sleep Apnea. Eur Respir J. 2025...");
        # cut the title at the first sentence boundary, keep the rest as tail.
        sm = _SENTENCE.search(title_parts[0], 20)
        if sm:
            rest = title_parts[0][sm.end():]
            title_parts[0] = title_parts[0][: sm.start()]
            tail.insert(0, rest)

    authors = _parse_authors(author_segs)
    if not authors:
        failed.append("authors")
    else:
        first_last = authors[0].split()[-1]
        if _INITIALS.match(first_last) or len(first_last.strip(".")) < 2:
            # The slug keys on the first author's surname — if that token is
            # an initial, the author run was misread. Punt to the LLM.
            failed.append("authors")
        elif len(authors) == 1 and len(authors[0].split()) == 1:
            # A lone bare token ("Hearing") is a misread title word, not an
            # author — real CV entries always carry initials or a given name.
            failed.append("authors")
    if any(re.fullmatch(r"(?:[A-Z]\.)+", seg) for seg in tail):
        # Dotted-initials segments *after* the title ("Fisher, B.,") mean the
        # entry is title-first (course notes, edited works) and the author
        # run was misplaced. Plain caps ("CA", "USA") are locations — fine.
        failed.append("authors")

    title = ", ".join(title_parts).strip(" .")
    words = title.split()
    if not (3 <= len(words) and 15 <= len(title) <= 400):
        failed.append("title")
    elif words[-1].lower().strip(":?") in _DANGLING:
        failed.append("title")  # cut off mid-phrase: boundary was wrong
    elif words[0][0].islower() and words[0].lower() in _DANGLING:
        # A title can't *start* mid-phrase either — this happens when a
        # title-first entry ("Hearing, Seeing and Touching: ...") had its
        # leading words mistaken for an author run.
        failed.append("title")
    elif re.match(r"(?:Proc\.|Proceedings\b|In Proc)", title):
        failed.append("title")  # that's a venue — the real title was missed

    if failed:
        return None, failed

    venue_parts: list[str] = []
    for seg in tail:
        if _TAIL_STOP.search(seg):
            break
        venue_parts.append(seg)
    venue = ", ".join(venue_parts).strip(" .")[:150] or None

    try:
        pub = Publication(
            id=slug_for(authors, year, title),
            title=title,
            authors=authors,
            year=year,
            type=entry.section.pub_type,
            venue=venue,
            link=link,
        )
    except ValidationError as e:
        return None, sorted({str(err["loc"][0]) for err in e.errors()})
    return pub, []


# --------------------------------------------------------------------------- #
# Section-level driver (deterministic only — the LLM fallback lives in cv.py)


def parse_cv_entries(
    section_text: str,
) -> tuple[list[Publication], list[CVEntry], list[ParseOutcome]]:
    """Split + deterministically parse a publications section.

    Returns ``(publications, failed_entries, outcomes)``: the entries that
    parsed cleanly, the ones needing the LLM fallback, and one
    :class:`ParseOutcome` per attempted entry (paths ``deterministic`` /
    ``failed`` — cv.py upgrades recovered failures to ``llm``).
    """

    pubs: list[Publication] = []
    failed_entries: list[CVEntry] = []
    outcomes: list[ParseOutcome] = []
    for entry in split_entries(section_text):
        pub, failed_fields = parse_entry(entry)
        if pub is not None:
            pubs.append(pub)
            outcomes.append(
                ParseOutcome(
                    path="deterministic",
                    section=entry.section.value,
                    slug=pub.id,
                    entry_preview=_preview(entry.text),
                )
            )
        else:
            failed_entries.append(entry)
            outcomes.append(
                ParseOutcome(
                    path="failed",
                    section=entry.section.value,
                    failed_fields=failed_fields,
                    entry_preview=_preview(entry.text),
                    error=f"deterministic parse failed: {', '.join(failed_fields)}",
                )
            )
    return pubs, failed_entries, outcomes
