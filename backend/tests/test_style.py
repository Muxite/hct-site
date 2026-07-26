"""Unit tests for document reading + style analysis (LLM faked)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.style import (
    _DEFAULT_STYLE_SYSTEM,
    analyze_style,
    check_profile,
    load_style_system_prompt,
    read_text_input,
    strip_profile_preamble,
)

_TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "templates"


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system, user, **kw):
        self.calls.append({"system": system, "user": user, "kw": kw})
        return self.response


class ScriptedLLM:
    """Returns each canned response in turn (first call, then the repair retry)."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, system, user, **kw):
        self.calls.append({"system": system, "user": user, "kw": kw})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def _make_docx(path, paragraphs):
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    doc = (
        '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
        + body
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc)


def test_read_docx_extracts_paragraph_text(tmp_path):
    p = tmp_path / "cv.docx"
    _make_docx(p, ["Sidney Fels is a professor.", "He studies HCI &amp; modeling."])
    text = read_text_input(p)
    assert "Sidney Fels is a professor." in text
    assert "He studies HCI & modeling." in text  # entity unescaped


def test_read_docx_breaks_paragraphs_into_lines(tmp_path):
    # Regression: paragraph breaks used to be substituted into the XML *between*
    # <w:t> runs and then dropped, so the whole document came back as one line.
    p = tmp_path / "cv.docx"
    _make_docx(p, ["Paper A, 2020.", "Paper B, 2019."])
    assert read_text_input(p).splitlines() == ["Paper A, 2020.", "Paper B, 2019."]


def test_read_plain_text(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("# Heading\nSome prose.", encoding="utf-8")
    assert read_text_input(p) == "# Heading\nSome prose."


def test_read_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_text_input(tmp_path / "nope.docx")


def test_analyze_style_calls_llm_in_text_mode():
    llm = FakeLLM("Tone: formal. Prefer active voice.")
    profile = analyze_style("Some academic text here.", llm=llm)
    assert profile == "Tone: formal. Prefer active voice."
    assert llm.calls[0]["kw"]["json_mode"] is False


def test_analyze_style_truncates_long_input():
    llm = FakeLLM("Tone: formal. Prefer active voice.")
    analyze_style("x" * 50000, llm=llm, max_chars=100)
    assert len(llm.calls[0]["user"]) < 200  # snippet, not the whole thing


def test_analyze_empty_text_raises():
    with pytest.raises(ValueError):
        analyze_style("   ", llm=FakeLLM("x"))


# --------------------------------------------------------------------------- #
# The profile describes voice, not layout
# --------------------------------------------------------------------------- #
def test_style_prompt_asks_for_voice_not_formatting():
    # A profile that prescribes bullets/bolding fights the summary styles that
    # require a specific markdown shape (e.g. style C's bold labels).
    lowered = _DEFAULT_STYLE_SYSTEM.lower()
    assert "tone" in lowered and "diction" in lowered and "rhythm" in lowered
    assert "do not describe layout" in lowered
    for banned in ("bullets", "bolding", "headings"):
        assert banned in lowered  # named, as things NOT to describe
    assert "no preamble" in lowered


def test_shipped_style_template_asks_for_voice_not_formatting():
    # The template file overrides the module default at runtime.
    text = load_style_system_prompt(_TEMPLATES)
    assert text != _DEFAULT_STYLE_SYSTEM  # the file really is being read
    lowered = text.lower()
    assert "voice only" in lowered
    assert "do not describe layout" in lowered
    assert "no preamble" in lowered


# --------------------------------------------------------------------------- #
# Profile sanity checking
# --------------------------------------------------------------------------- #
def test_strip_preamble_drops_a_lead_in_line():
    raw = "Here is the style profile:\nTone: formal. Prefer active voice."
    assert strip_profile_preamble(raw) == "Tone: formal. Prefer active voice."


def test_strip_preamble_drops_an_inline_lead_in():
    raw = "Sure, here is the profile: Tone is formal and the voice is active."
    assert strip_profile_preamble(raw) == "Tone is formal and the voice is active."


def test_strip_preamble_leaves_a_clean_profile_alone():
    raw = "Tone: formal. Prefer active voice; avoid hype."
    assert strip_profile_preamble(raw) == raw


def test_check_profile_accepts_a_normal_profile():
    assert check_profile("Tone: formal. Prefer active voice; avoid hype.") == ""


def test_check_profile_rejects_empty_and_runaway_responses():
    assert check_profile("   ") != ""
    assert check_profile("word " * 500) != ""


def test_analyze_style_strips_a_preamble_without_retrying():
    llm = FakeLLM("Here is the profile:\nTone: formal. Prefer active voice.")
    assert analyze_style("Some text.", llm=llm) == "Tone: formal. Prefer active voice."
    assert len(llm.calls) == 1  # stripped, not retried


def test_analyze_style_retries_once_on_a_malformed_response():
    llm = ScriptedLLM("Sure! " + "padding " * 400, "Tone: formal. Prefer active voice.")
    assert analyze_style("Some text.", llm=llm) == "Tone: formal. Prefer active voice."
    assert len(llm.calls) == 2
    assert "rejected" in llm.calls[1]["system"]
    assert llm.calls[1]["kw"]["label"] == "style-repair"


def test_analyze_style_raises_when_the_retry_is_also_malformed():
    llm = ScriptedLLM("word " * 500)
    with pytest.raises(ValueError, match="malformed"):
        analyze_style("Some text.", llm=llm)
    assert len(llm.calls) == 2  # exactly one repair retry, then give up
