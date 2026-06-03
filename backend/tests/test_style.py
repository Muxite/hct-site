"""Unit tests for document reading + style analysis (LLM faked)."""

from __future__ import annotations

import zipfile

import pytest

from src.style import analyze_style, read_text_input


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system, user, **kw):
        self.calls.append({"system": system, "user": user, "kw": kw})
        return self.response


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
    llm = FakeLLM("ok")
    analyze_style("x" * 50000, llm=llm, max_chars=100)
    assert len(llm.calls[0]["user"]) < 200  # snippet, not the whole thing


def test_analyze_empty_text_raises():
    with pytest.raises(ValueError):
        analyze_style("   ", llm=FakeLLM("x"))
