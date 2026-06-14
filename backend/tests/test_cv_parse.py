"""Unit tests for the deterministic CV entry parser (no LLM, no network)."""

from __future__ import annotations

from src.cv_parse import (
    CVEntry,
    CVSection,
    classify_section,
    parse_cv_entries,
    parse_entry,
    split_entries,
)
from src.models import PubType

# Fixture lines copied from a real UBC-form CV (truncated where long).
JOURNAL_LINE = (
    "Ashjaee, N. Street, J., Fels, S., and Oxland, T., Machine Learning "
    "Outperforms Anthropometric Scaling in Predicting Muscle Parameters and "
    "Spinal Loading: A Subject-Specific Musculoskeletal Modeling study. "
    "(2026), European Spine Journal, 10pp. "
    "https://doi.org/10.1007/s00586-026-09878-1"
)
NBSP_LINE = (
    "Victor Zappi,\xa0Andrew Allen, and\xa0Sidney Fels, Extended Playing "
    "Techniques on an Augmented Virtual Percussion Instrument, Computer Music "
    "Journal, Vol. 42, No. 02,\xa0pp. 8–21, 2018. doi.org/10.1162/comj_a_00457\xa0"
)
COMPACT_LINE = (
    "Hajipour M, Hicks JB, Hirsch Allen AJ, Fels S, Ayas NT. Respiratory "
    "Event-related Physiological Biomarkers and Cognitive Performance in "
    "Obstructive Sleep Apnea. Eur Respir J. 2025 Jul 12. doi: 10.1183/13993003.00201-2025"
)
SECTION_TEXT = """Publications Record
SURNAME: FelsFIRST NAME: SolInitials:
MIDDLE NAME (S): SidneyDate: 26 / Aug / 2024
Those publications considered to be of primary importance are indicated by an asterisk.
1.REFEREED PUBLICATIONS
(a)Journal
{journal}
(b)Conference & Workshop Proceedings
{nbsp}
2.NON-REFEREED PUBLICATIONS
(a)Journals
{compact}
""".format(journal=JOURNAL_LINE, nbsp=NBSP_LINE, compact=COMPACT_LINE)

# A multi-line entry: authors split across paragraphs, year only on the last.
MULTILINE = """1.REFEREED PUBLICATIONS
(a)Journal
Valéria de Cássia Sparapani, Sidney Fels,
Noreen Kamal,
Lucila Castanheira Nascimento,
Conceptual framework for designing video games for children with type 1 diabetes, Revista Latino-Americana de Enfermagem, 27:e3090, 12 pages, 2019. DOI: 10.1590/1518-8345.2764.3090
Lloyd, J., Sanchez, A, and Fels, S., New Techniques for Combined FEM-Multibody Anatomical Simulation, Journal of Biomechanics, vol 8, 2019.
"""


def test_split_entries_skips_preamble_and_tracks_sections():
    entries = split_entries(SECTION_TEXT)
    assert len(entries) == 3
    assert entries[0].section is CVSection.journal
    assert entries[1].section is CVSection.conference
    assert entries[2].section is CVSection.journal
    assert entries[0].text.startswith("Ashjaee")
    # NBSPs normalized away in the joined text
    assert "\xa0" not in entries[1].text


def test_split_entries_joins_multiline_entry():
    entries = split_entries(MULTILINE)
    assert len(entries) == 2
    assert entries[0].text.startswith("Valéria")
    assert "Conceptual framework" in entries[0].text
    assert entries[1].text.startswith("Lloyd")


def test_split_entries_without_headers_processes_all_lines():
    text = JOURNAL_LINE + "\n" + COMPACT_LINE + "\n"
    entries = split_entries(text)
    assert len(entries) == 2
    assert all(e.section is CVSection.unknown for e in entries)


def test_classify_section_mappings():
    assert classify_section("1.REFEREED PUBLICATIONS", "Journal") is CVSection.journal
    assert (
        classify_section("1.REFEREED PUBLICATIONS", "Conference & Workshop Proceedings")
        is CVSection.conference
    )
    assert (
        classify_section("1.REFEREED PUBLICATIONS", "Book Chapters (peer-reviewed)")
        is CVSection.book_chapter
    )
    assert classify_section("3.BOOKS", "Authored") is CVSection.book
    assert classify_section("3.BOOKS", "Chapters") is CVSection.book_chapter
    assert classify_section("4.PATENTS", "") is CVSection.patent
    assert classify_section("6.ARTISTIC WORKS", "") is CVSection.other
    assert classify_section("", "") is CVSection.unknown
    assert CVSection.journal.pub_type is PubType.article
    assert CVSection.conference.pub_type is PubType.inproceedings


def test_parse_entry_journal_with_paren_year_and_doi():
    pub, failed = parse_entry(CVEntry(text=JOURNAL_LINE, section=CVSection.journal))
    assert failed == []
    assert pub.year == 2026
    assert pub.type is PubType.article
    assert pub.title.startswith("Machine Learning Outperforms")
    # Sloppy "Ashjaee, N. Street, J." run is repaired into four authors.
    assert pub.authors == ["N. Ashjaee", "J Street", "S Fels", "T Oxland"]
    assert pub.id.startswith("ashjaee2026-")
    assert pub.link == "https://doi.org/10.1007/s00586-026-09878-1"
    assert pub.venue == "European Spine Journal"


def test_parse_entry_full_names_with_nbsp_and_bare_doi():
    pub, failed = parse_entry(CVEntry(text=NBSP_LINE, section=CVSection.journal))
    assert failed == []
    assert pub.authors == ["Victor Zappi", "Andrew Allen", "Sidney Fels"]
    assert pub.year == 2018  # the DOI's digit runs must not win
    assert pub.title == "Extended Playing Techniques on an Augmented Virtual Percussion Instrument"
    assert pub.venue == "Computer Music Journal"
    assert pub.link == "https://doi.org/10.1162/comj_a_00457"


def test_parse_entry_compact_initials_style():
    pub, failed = parse_entry(CVEntry(text=COMPACT_LINE, section=CVSection.journal))
    assert failed == []
    # "Hajipour M" normalized so the slug keys on the surname.
    assert pub.authors[0] == "M Hajipour"
    assert pub.authors[2] == "AJ Hirsch Allen"
    assert pub.id.startswith("hajipour2025-")
    assert pub.year == 2025


def test_parse_entry_fails_without_year():
    entry = CVEntry(
        text="Fels, S., Position statement for Panel on Nonverbal Information "
        "Processing, Proceedings of the Workshop on VLBV'XX, pg. 5",
        section=CVSection.conference,
    )
    pub, failed = parse_entry(entry)
    assert pub is None
    assert "year" in failed


def test_parse_entry_fails_on_title_first_entry():
    # Title-first entries (course notes etc.) must fail to the LLM, not parse
    # their leading words as authors.
    entry = CVEntry(
        text="Hearing, Seeing and Touching: Putting It All Together, Fisher, "
        "B., Munzner, T., Course notes of ACM SIGGRAPH, 2000.",
        section=CVSection.other,
    )
    pub, failed = parse_entry(entry)
    assert pub is None
    assert failed  # ambiguous -> punt


def test_parse_entry_fails_on_garbage():
    pub, failed = parse_entry(
        CVEntry(text="lorem ipsum dolor sit amet 42", section=CVSection.unknown)
    )
    assert pub is None
    assert failed


def test_parse_cv_entries_outcomes():
    pubs, failed_entries, outcomes = parse_cv_entries(SECTION_TEXT)
    assert len(pubs) == 3
    assert failed_entries == []
    assert [o.path for o in outcomes] == ["deterministic"] * 3
    assert {o.section for o in outcomes} == {"journal", "conference"}
    assert all(o.slug for o in outcomes)
    assert all(o.entry_preview for o in outcomes)


def test_parse_cv_entries_records_failures():
    text = (
        "1.REFEREED PUBLICATIONS\n(a)Journal\n"
        + JOURNAL_LINE
        + "\nFels, S., An entry with a title but no any-digit year at all, Some Venue, pp. 1-2.\n"
    )
    pubs, failed_entries, outcomes = parse_cv_entries(text)
    assert len(pubs) == 1
    assert len(failed_entries) == 1
    assert [o.path for o in outcomes] == ["deterministic", "failed"]
    assert outcomes[1].failed_fields == ["year"]
    assert outcomes[1].error and "year" in outcomes[1].error
