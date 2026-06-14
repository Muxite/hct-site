"""Unit tests for the CV source: docx reading, section trim, deterministic-first
extraction with per-entry LLM fallback.

The LLM is always faked; no network.
"""

from __future__ import annotations

import json
import zipfile

from src.cv import extract_cv_publications, publications_section, read_cv_text
from src.metrics import ParseTracker


class FakeLLM:
    """Returns canned publications keyed by a needle found in the user prompt."""

    def __init__(self, by_text):
        self.by_text = by_text
        self.calls: list[str] = []

    def complete(self, *, system, user, **kw):
        self.calls.append(user)
        for needle, pubs in self.by_text.items():
            if needle in user:
                return json.dumps({"publications": pubs})
        return json.dumps({"publications": []})


# --- docx reading -----------------------------------------------------------

def _make_docx(path, body_xml):
    doc = (
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        + body_xml
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc)


def test_read_cv_text_docx(tmp_path):
    p = tmp_path / "cv.docx"
    _make_docx(p, "<w:p><w:r><w:t>PUBLICATIONS</w:t></w:r></w:p>")
    assert read_cv_text(p) == "PUBLICATIONS"


def test_read_cv_text_does_not_leak_xml_on_tabs(tmp_path):
    # Regression: <w:tab/> used to match the <w:t...> opening pattern, swallowing
    # everything up to the next </w:t> — tab-heavy forms (UBC CV) came back as XML.
    p = tmp_path / "cv.docx"
    _make_docx(
        p,
        "<w:p><w:r><w:tab/><w:t>SURNAME: Fels</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Glove-TalkII, 1998.</w:t></w:r></w:p>",
    )
    text = read_cv_text(p)
    assert "SURNAME: Fels" in text
    assert "Glove-TalkII, 1998." in text
    assert "<w:" not in text


# --- section trimming -------------------------------------------------------

def test_publications_section_finds_ubc_record_heading():
    text = "biography stuff\nawards\nPublications Record\nPaper A, 2020.\nPaper B, 2019."
    section = publications_section(text)
    assert section.startswith("Publications Record")
    assert "biography stuff" not in section
    assert "Paper B, 2019." in section


def test_publications_section_finds_refereed_heading_case_insensitive():
    text = "intro\n1.Refereed Publications\n(a)Journal\nPaper A, 2020."
    assert publications_section(text).startswith("Refereed Publications")


def test_publications_section_falls_back_to_full_text():
    text = "Paper A, 2020.\nPaper B, 2019."
    assert publications_section(text) == text  # unknown layout -> keep everything


# --- deterministic-first extraction -------------------------------------------

# Entries that the deterministic heuristics parse cleanly.
GOOD_JOURNAL = (
    "Ashjaee, N. Street, J., Fels, S., and Oxland, T., Machine Learning "
    "Outperforms Anthropometric Scaling in Predicting Muscle Parameters. "
    "(2026), European Spine Journal, 10pp."
)
GOOD_CONF = (
    "Victor Zappi, Andrew Allen, and Sidney Fels, Extended Playing Techniques "
    "on an Augmented Virtual Percussion Instrument, Computer Music Journal, "
    "Vol. 42, No. 02, pp. 8–21, 2018."
)
# A title-first entry the heuristics must punt on (-> LLM fallback).
BAD_ENTRY = (
    "Hearing, Seeing and Touching: Putting It All Together, Fisher, B., "
    "Munzner, T., Course notes of ACM SIGGRAPH, 2000."
)

CV_TEXT = (
    "Publications Record\n"
    "SURNAME: Fels\n"
    "1.REFEREED PUBLICATIONS\n"
    "(a)Journal\n" + GOOD_JOURNAL + "\n"
    "(b)Conference & Workshop Proceedings\n" + GOOD_CONF + "\n"
    "7.OTHER WORKS\n" + BAD_ENTRY + "\n"
)

LLM_FIXED = [{
    "title": "Hearing, Seeing and Touching: Putting It All Together",
    "authors": ["B. Fisher", "T. Munzner"],
    "year": 2000,
    "type": "misc",
}]


def test_all_deterministic_means_zero_llm_calls():
    cv_text = (
        "Publications Record\n1.REFEREED PUBLICATIONS\n(a)Journal\n"
        + GOOD_JOURNAL + "\n" + GOOD_CONF + "\n"
    )
    llm = FakeLLM({})
    ps = extract_cv_publications(cv_text, llm=llm)
    assert llm.calls == []  # the whole CV cost zero LLM tokens
    assert sorted(p.id[:4] for p in ps.publications) == ["ashj", "zapp"]


def test_failed_entry_routed_to_llm_and_recovered():
    llm = FakeLLM({"Hearing": LLM_FIXED})
    tracker = ParseTracker()
    ps = extract_cv_publications(CV_TEXT, llm=llm, parse_tracker=tracker)
    # Only the bad entry went to the LLM — and alone, not with the whole CV.
    assert len(llm.calls) == 1
    assert "Hearing" in llm.calls[0]
    assert GOOD_JOURNAL[:30] not in llm.calls[0]
    titles = {p.title for p in ps.publications}
    assert "Hearing, Seeing and Touching: Putting It All Together" in titles
    s = tracker.summary
    assert s["total"] == 3
    assert s["deterministic"] == 2 and s["llm"] == 1 and s["failed"] == 0
    llm_recs = [r for r in tracker.records if r.path == "llm"]
    assert llm_recs[0].slug == "fisher2000-hearing-seeing-and-touching-putting-it-all"
    assert llm_recs[0].error is None


def test_unrecoverable_entry_recorded_as_failed():
    llm = FakeLLM({})  # returns no publications for the bad entry
    tracker = ParseTracker()
    ps = extract_cv_publications(CV_TEXT, llm=llm, parse_tracker=tracker)
    assert len(ps.publications) == 2  # bad entry absent from the set
    s = tracker.summary
    assert s["failed"] == 1
    failed = [r for r in tracker.records if r.path == "failed"]
    assert "llm fallback returned no entries" in failed[0].error


def test_outcomes_carry_sections():
    llm = FakeLLM({"Hearing": LLM_FIXED})
    tracker = ParseTracker()
    extract_cv_publications(CV_TEXT, llm=llm, parse_tracker=tracker)
    assert {r.section for r in tracker.records} == {"journal", "conference", "other"}


def test_dedupes_across_cv_subsections():
    cv_text = (
        "PUBLICATIONS\n1.REFEREED PUBLICATIONS\n(a)Journal\n"
        + GOOD_JOURNAL + "\n(b)Conference & Workshop Proceedings\n"
        + GOOD_JOURNAL + "\n"
    )
    ps = extract_cv_publications(cv_text, llm=FakeLLM({}))
    assert len(ps.publications) == 1


def test_skips_preamble():
    cv_text = "SECRET BIO LINE\n" + CV_TEXT
    llm = FakeLLM({"Hearing": LLM_FIXED})
    extract_cv_publications(cv_text, llm=llm)
    assert all("SECRET BIO LINE" not in u for u in llm.calls)


def test_works_without_tracker():
    ps = extract_cv_publications(CV_TEXT, llm=FakeLLM({"Hearing": LLM_FIXED}))
    assert len(ps.publications) == 3
