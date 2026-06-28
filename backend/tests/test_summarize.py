"""Unit tests for the paper summary generator (styles A-E, fake LLM)."""

from __future__ import annotations

from src.models import Publication
from src.summarize import (
    STYLES,
    SummaryEval,
    build_summary_prompt,
    evaluate_summary,
    resolve_style,
    sanitize_summary,
    summarize_paper,
)


def _pub(**kw) -> Publication:
    base = dict(
        id="zhu2022-control-logic",
        title="A unified representation of control logic",
        authors=["Hongzhi Zhu", "Sidney Fels"],
        year=2022,
        venue="Journal of Examples",
    )
    base.update(kw)
    return Publication(**base)


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, **kw) -> str:
        self.calls.append({"system": system, "user": user, **kw})
        return self.reply


# --------------------------------------------------------------------------- #
# Styles + prompt building
# --------------------------------------------------------------------------- #
def test_five_styles_present():
    assert sorted(STYLES) == ["A", "B", "C", "D", "E"]


def test_resolve_style_key_and_literal():
    assert resolve_style("A") == STYLES["A"]
    assert resolve_style("my custom profile") == "my custom profile"


def test_prompt_includes_style_facts_and_grounding():
    prompt = build_summary_prompt(_pub(), style_profile=STYLES["C"], context="We trained a CNN.")
    assert "Problem:" in prompt  # style C injected
    assert "A unified representation of control logic" in prompt
    assert "Hongzhi Zhu; Sidney Fels" in prompt
    assert "use only this for facts" in prompt
    assert "We trained a CNN." in prompt


def test_prompt_without_context_warns_not_to_invent():
    prompt = build_summary_prompt(_pub(), style_profile=STYLES["A"], context="")
    assert "do not invent" in prompt


# --------------------------------------------------------------------------- #
# summarize_paper
# --------------------------------------------------------------------------- #
def test_summarize_paper_sanitizes_and_passes_style():
    llm = FakeLLM("The method, a CNN, improves accuracy — clearly. 🎉")
    out = summarize_paper(_pub(), llm=llm, style="B", context="A CNN improves accuracy.")
    assert "—" not in out and "🎉" not in out
    assert "," in out  # em dash became a comma
    # The style B profile reached the model.
    assert STYLES["B"] in llm.calls[0]["user"]
    assert llm.calls[0]["json_mode"] is False
    assert llm.calls[0]["label"] == "summary"


# --------------------------------------------------------------------------- #
# sanitize_summary
# --------------------------------------------------------------------------- #
def test_sanitize_em_dash_to_comma():
    assert sanitize_summary("A — B") == "A, B"


def test_sanitize_en_dash_range_to_hyphen():
    assert sanitize_summary("pages 10–20 here") == "pages 10-20 here"


def test_sanitize_other_en_dash_to_comma():
    assert sanitize_summary("cats – dogs") == "cats, dogs"


def test_sanitize_strips_emoji_keeps_arrows():
    assert sanitize_summary("input → output 🚀✨") == "input → output"


def test_sanitize_preserves_bullets():
    out = sanitize_summary("- one\n- two\n- three")
    assert out == "- one\n- two\n- three"


# --------------------------------------------------------------------------- #
# evaluate_summary
# --------------------------------------------------------------------------- #
def test_evaluate_clean_summary():
    s = "A grounded overview of the method and its measured accuracy gain over the prior baseline approach."
    ev = evaluate_summary(s, _pub(), source_text="method accuracy baseline")
    assert isinstance(ev, SummaryEval)
    assert ev.clean is True
    assert ev.flags == "ok"


def test_evaluate_flags_em_dash_and_emoji():
    ev = evaluate_summary("A method — really good 🎉 with lots of useful detail here now", _pub())
    assert ev.has_em_dash is True
    assert ev.has_emoji is True
    assert ev.clean is False
    assert "M" in ev.flags and "E" in ev.flags


def test_evaluate_flags_filler_opening_and_title_echo():
    s = "This paper presents a unified representation of control logic for systems."
    ev = evaluate_summary(s, _pub())
    assert ev.filler_opening is True
    assert ev.repeats_title is True


def test_evaluate_flags_ungrounded_numbers():
    ev = evaluate_summary(
        "The approach reaches 99 percent accuracy across many varied evaluation trials.",
        _pub(),
        source_text="the approach improves accuracy",
    )
    assert "99" in ev.ungrounded_numbers


def test_evaluate_flags_too_short():
    ev = evaluate_summary("Too short.", _pub())
    assert ev.too_short is True


def test_evaluate_thousands_separator_not_ungrounded():
    # "10,000" in the summary must match "10000" in the source (no spurious "000").
    ev = evaluate_summary(
        "The review screened over 10,000 records across many databases and sources here.",
        _pub(),
        source_text="we screened 10000 records",
    )
    assert ev.ungrounded_numbers == []
