"""Data QA: validate what the AI wrote into Supabase, as a plain-text report.

``hct-manager qa`` pulls the live rows from every table and runs four families of
checks and emits a diffable ``state/qa-report.txt``:

* **schema/consistency** — re-validate each publication against the Pydantic
  model (year bounds, URL, non-empty authors come "for free"), catch duplicate
  slugs, dangling timeline references, position gaps.
* **completeness** — flag missing AI-written prose and thin fields.
* **AI-writing sanity** — heuristics over every AI-written text field: length,
  model-tell filler phrases, markdown leakage, echoed titles, invented numbers.
* **source cross-check** — best-effort match of DB rows against the static page,
  to surface stale or hallucinated entries.

Everything here is pure functions over plain ``dict`` rows so the logic is
testable without a network: the CLI fetches the rows, ``run_qa`` does the work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import ValidationError

from src.content import _SECTION_KEYS, publications_block_text
from src.models import Publication

# Severity levels, ordered most-to-least urgent for rendering.
ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"
_SEV_ORDER = {ERROR: 0, WARN: 1, INFO: 2}

# Categories, in the order they appear in the report.
_CAT_ORDER = ["schema", "completeness", "ai", "source"]
_CAT_TITLES = {
    "schema": "SCHEMA & CONSISTENCY",
    "completeness": "COMPLETENESS",
    "ai": "AI-WRITING SANITY",
    "source": "SOURCE CROSS-CHECK",
}

# Tables in summary order. ``site_content`` is keyed, the rest are row lists.
_TABLES = ["publications", "timeline", "people", "research", "site_content"]

# --- AI-writing heuristics -------------------------------------------------
_MIN_PROSE_CHARS = 40
_MAX_PROSE_CHARS = 600
_MAX_SENTENCES = 5
# Phrases that read as LLM filler / model-tells rather than lab voice.
_FILLER_PHRASES = (
    "as an ai",
    "as a language model",
    "in conclusion",
    "in summary",
    "it is important to note",
    "it should be noted",
    "this paper",
    "this study",
    "this work presents",
    "delve",
    "leverage",
)
# Markdown that should never reach a plain-text prose field.
_MARKDOWN_RE = re.compile(r"(`|\*\*|^#{1,6}\s|^\s*[-*]\s)", re.MULTILINE)
# Invented-specifics signals — prompts say never invent numbers/results.
_NUMBER_RES = (
    re.compile(r"\d+(?:\.\d+)?\s*%"),
    re.compile(r"\bn\s*=\s*\d+", re.IGNORECASE),
)

# Which field on each table is AI-written prose, and a label-bearing field used
# to detect a title/name echoed back into the prose (None = skip echo check).
_AI_TEXT_FIELDS = {
    "publications": ("description", "title"),
    "timeline": ("blurb", "title"),
    "research": ("description", "title"),
    "people": ("bio", None),
}


@dataclass
class Finding:
    severity: str  # ERROR | WARN | INFO
    category: str  # schema | completeness | ai | source
    table: str
    ref: str       # row identity: slug / pos=N / name / title / key
    message: str


@dataclass
class StaticSource:
    """The static page parsed into the bits the cross-check compares against."""

    pub_text: str = ""              # lowercased text of the #publications-static block
    people_names: list[str] = field(default_factory=list)


def build_source(
    index_html: str, *, people_names: list[str] | None = None
) -> StaticSource:
    """Build the cross-check source: publication text from the static page,
    people names from ``people.yaml`` (the roster's source of truth) when the
    caller has them."""

    return StaticSource(
        pub_text=publications_block_text(index_html).lower(),
        people_names=list(people_names or []),
    )


# --- ref helpers -----------------------------------------------------------
def _pub_ref(row: dict) -> str:
    return str(row.get("slug") or row.get("id") or "?")


def _timeline_ref(row: dict) -> str:
    return f"pos={row.get('position')}"


def _blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


# --- schema & consistency --------------------------------------------------
def _schema_checks(rows: dict[str, list[dict]]):
    pubs = rows.get("publications", [])

    # Re-validate each publication row through the Pydantic model — this reuses
    # the model's validators (year bounds, http(s) link, non-empty authors,
    # known type enum) instead of re-implementing them here.
    for row in pubs:
        try:
            Publication.model_validate({**row, "id": row.get("slug") or row.get("id")})
        except ValidationError as exc:
            errs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            yield Finding(ERROR, "schema", "publications", _pub_ref(row), f"invalid row — {errs}")

    # Duplicate slugs collide on the unique key and silently merge.
    seen: set[str] = set()
    for row in pubs:
        slug = row.get("slug")
        if not slug:
            continue
        if slug in seen:
            yield Finding(ERROR, "schema", "publications", slug, "duplicate slug")
        seen.add(slug)

    # Timeline references and ordering.
    tl = rows.get("timeline", [])
    pub_slugs = {row.get("slug") for row in pubs if row.get("slug")}
    positions: list[int] = []
    for row in tl:
        ref = _timeline_ref(row)
        slug = row.get("slug")
        if slug and slug not in pub_slugs:
            yield Finding(ERROR, "schema", "timeline", ref, f"slug '{slug}' has no matching publication")
        pos = row.get("position")
        if isinstance(pos, int):
            positions.append(pos)
    if len(positions) != len(set(positions)):
        yield Finding(ERROR, "schema", "timeline", "*", "duplicate position values")
    elif positions and sorted(positions) != list(range(len(positions))):
        yield Finding(WARN, "schema", "timeline", "*", f"positions not contiguous from 0: {sorted(positions)}")
    # The timeline mirrors the full publication history (newest first); flag only
    # a count mismatch against publications, not a fixed expected size.
    if tl and pubs and len(tl) != len(pubs):
        yield Finding(
            WARN, "schema", "timeline", "*",
            f"{len(tl)} entries but {len(pubs)} publications (expected one per paper)",
        )


# --- completeness ----------------------------------------------------------
def _completeness_checks(rows: dict[str, list[dict]]):
    for row in rows.get("publications", []):
        ref = _pub_ref(row)
        if _blank(row.get("description")):
            yield Finding(WARN, "completeness", "publications", ref, "no description (AI blurb missing)")
        if _blank(row.get("venue")):
            yield Finding(INFO, "completeness", "publications", ref, "no venue")
        if _blank(row.get("link")):
            yield Finding(INFO, "completeness", "publications", ref, "no link")

    for row in rows.get("timeline", []):
        ref = _timeline_ref(row)
        # The full history won't have a blurb for every historical paper — info,
        # not a warning. A missing slug link, though, breaks the paper detail link.
        if _blank(row.get("blurb")):
            yield Finding(INFO, "completeness", "timeline", ref, "no blurb (AI text missing)")
        if _blank(row.get("slug")):
            yield Finding(WARN, "completeness", "timeline", ref, "no slug link to a publication")

    for row in rows.get("people", []):
        ref = row.get("name") or "?"
        if _blank(row.get("bio")):
            yield Finding(WARN, "completeness", "people", ref, "no bio (AI text missing)")
        if _blank(row.get("role")):
            yield Finding(INFO, "completeness", "people", ref, "no role")
        if _blank(row.get("email")) and _blank(row.get("photo")):
            yield Finding(INFO, "completeness", "people", ref, "no email or photo")

    for row in rows.get("research", []):
        ref = row.get("title") or "?"
        if _blank(row.get("description")):
            yield Finding(WARN, "completeness", "research", ref, "no description (AI text missing)")
        if _blank(row.get("tagline")):
            yield Finding(INFO, "completeness", "research", ref, "no tagline")

    present = {row.get("key") for row in rows.get("site_content", [])}
    for key in sorted(set(_SECTION_KEYS.values())):
        if key not in present:
            yield Finding(WARN, "completeness", "site_content", key, "expected section key missing")


# --- AI-writing sanity -----------------------------------------------------
def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+", text) if s.strip()])


def _ai_text_findings(table: str, ref: str, text: str, echo: str | None):
    """Heuristic checks on one AI-written prose field. Yields WARN findings."""

    stripped = text.strip()
    n = len(stripped)
    if n < _MIN_PROSE_CHARS:
        yield Finding(WARN, "ai", table, ref, f"prose very short ({n} chars)")
    if n > _MAX_PROSE_CHARS:
        yield Finding(WARN, "ai", table, ref, f"prose very long ({n} chars > {_MAX_PROSE_CHARS})")
    sents = _sentence_count(stripped)
    if sents > _MAX_SENTENCES:
        yield Finding(WARN, "ai", table, ref, f"{sents} sentences (>{_MAX_SENTENCES})")

    low = stripped.lower()
    hits = [p for p in _FILLER_PHRASES if p in low]
    if hits:
        yield Finding(WARN, "ai", table, ref, "filler/model-tell phrase: " + ", ".join(repr(h) for h in hits))

    if _MARKDOWN_RE.search(stripped):
        yield Finding(WARN, "ai", table, ref, "markdown leaked into plain-text field")

    if echo:
        head = echo.strip().lower()[:40]
        if head and head in low:
            yield Finding(WARN, "ai", table, ref, "title/name echoed back in prose")

    for rx in _NUMBER_RES:
        if rx.search(stripped):
            yield Finding(WARN, "ai", table, ref, "numeric claim — verify it is not invented")
            break


def _ai_checks(rows: dict[str, list[dict]]):
    ref_fns = {"publications": _pub_ref, "timeline": _timeline_ref}
    for table, (field_name, echo_field) in _AI_TEXT_FIELDS.items():
        ref_fn = ref_fns.get(table)
        for row in rows.get(table, []):
            text = row.get(field_name)
            if _blank(text):
                continue  # absence is a completeness finding, not an AI-quality one
            if ref_fn:
                ref = ref_fn(row)
            else:
                ref = row.get("name") or row.get("title") or "?"
            echo = row.get(echo_field) if echo_field else None
            yield from _ai_text_findings(table, ref, text, echo)


# --- source cross-check ----------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _source_checks(rows: dict[str, list[dict]], source: StaticSource):
    if source.pub_text:
        for row in rows.get("publications", []):
            title = _norm(str(row.get("title") or ""))
            if title and title not in source.pub_text:
                yield Finding(
                    WARN, "source", "publications", _pub_ref(row),
                    "title not found in static page (possibly stale or hallucinated)",
                )

    page_names = {_norm(n) for n in source.people_names}
    if page_names:
        db_names = {_norm(str(row.get("name") or "")) for row in rows.get("people", [])}
        for row in rows.get("people", []):
            if _norm(str(row.get("name") or "")) not in page_names:
                yield Finding(WARN, "source", "people", row.get("name") or "?", "person not in people.yaml")
        for name in source.people_names:
            if _norm(name) not in db_names:
                yield Finding(INFO, "source", "people", name, "person in people.yaml but not in DB")


# --- report ----------------------------------------------------------------
@dataclass
class QAReport:
    rows: dict[str, list[dict]]
    findings: list[Finding]
    strict: bool = False
    source_url: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def n_errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == ERROR)

    @property
    def n_warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == WARN)

    @property
    def exit_code(self) -> int:
        if self.n_errors:
            return 1
        if self.strict and self.n_warnings:
            return 1
        return 0

    def _table_counts(self, table: str) -> tuple[int, int]:
        err = sum(1 for f in self.findings if f.table == table and f.severity == ERROR)
        warn = sum(1 for f in self.findings if f.table == table and f.severity == WARN)
        return err, warn

    def render(self) -> str:
        lines: list[str] = []
        bar = "=" * 70
        lines.append("HCT SITE — DATA QA REPORT")
        ts = self.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        src = f"   Source: {self.source_url}" if self.source_url else ""
        lines.append(f"Generated: {ts}{src}")
        lines.append(bar)
        lines.append("SUMMARY")
        for table in _TABLES:
            n = len(self.rows.get(table, []))
            unit = "keys" if table == "site_content" else "rows"
            err, warn = self._table_counts(table)
            lines.append(f"  {table:<14}{n:>3} {unit:<5}{err:>4} ERR {warn:>4} WARN")
        lines.append("  " + "-" * 60)
        status = "FAIL" if self.exit_code else "PASS"
        lines.append(f"  {'TOTAL':<14}{'':>9}{self.n_errors:>4} ERR {self.n_warnings:>4} WARN     STATUS: {status}")
        lines.append(bar)

        for cat in _CAT_ORDER:
            cat_findings = [f for f in self.findings if f.category == cat]
            if not cat_findings:
                continue
            lines.append(_CAT_TITLES[cat])
            cat_findings.sort(key=lambda f: (_SEV_ORDER[f.severity], f.table, f.ref))
            for f in cat_findings:
                tag = f"[{f.severity}]"
                loc = f"{f.table}/{f.ref}"
                lines.append(f"  {tag:<8}{loc:<42} {f.message}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def run_qa(
    rows: dict[str, list[dict]],
    *,
    source: StaticSource | None = None,
    strict: bool = False,
    source_url: str = "",
) -> QAReport:
    """Run every check family over ``rows`` and return a :class:`QAReport`."""

    findings: list[Finding] = []
    findings += list(_schema_checks(rows))
    findings += list(_completeness_checks(rows))
    findings += list(_ai_checks(rows))
    if source is not None:
        findings += list(_source_checks(rows, source))
    return QAReport(rows=rows, findings=findings, strict=strict, source_url=source_url)
