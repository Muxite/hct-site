"""Unit tests for the paper summary generator (styles A-E, fake LLM)."""

from __future__ import annotations

import re

from src.models import Publication
from src.summarize import (
    STYLES,
    SUMMARY_SYSTEM,
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


def test_voice_profile_appends_distinct_block_without_altering_style_profile():
    # voice_profile is the admin's lab-voice calibration text (style_profile.
    # profile_text) -- a genuinely separate prompt block from style_profile,
    # the audience-style (A/B/C/D/E) parameter. Supplying it must not change,
    # remove, or overwrite the style instruction already in the prompt.
    base = build_summary_prompt(_pub(), style_profile=STYLES["C"], context="We trained a CNN.")
    with_voice = build_summary_prompt(
        _pub(), style_profile=STYLES["C"], voice_profile="Crisp, active voice; short sentences.",
        context="We trained a CNN.",
    )
    assert with_voice != base
    assert "Crisp, active voice; short sentences." in with_voice
    assert "Crisp, active voice; short sentences." not in base
    # The style block is untouched -- same content, same leading position.
    style_prefix = f"Write the overview in this style:\n{STYLES['C'].strip()}\n"
    assert base.startswith(style_prefix)
    assert with_voice.startswith(style_prefix)


def test_voice_block_states_that_style_and_grounding_win():
    # Without a precedence rule the voice profile overrides the style's length
    # and shape constraints, which is exactly what a live test showed happening.
    prompt = build_summary_prompt(
        _pub(), style_profile=STYLES["C"], voice_profile="Long, discursive paragraphs.",
        context="",
    )
    lowered = prompt.lower()
    assert "the style and the grounding rules win" in lowered
    # The rule sits in the voice block, after the profile it qualifies.
    assert lowered.index("long, discursive paragraphs.") < lowered.index(
        "the style and the grounding rules win"
    )


def test_summary_system_prompt_practises_its_own_dash_ban():
    # The prompt bans em/en dashes; using them in the instruction itself teaches
    # the model the opposite register.
    assert not re.search(r"[—–]", SUMMARY_SYSTEM)


def test_voice_profile_omitted_when_blank():
    prompt = build_summary_prompt(_pub(), style_profile=STYLES["A"], voice_profile="   ", context="")
    assert "writing voice" not in prompt.lower()


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


def test_summarize_paper_passes_voice_profile_alongside_style():
    llm = FakeLLM("A steady overview.")
    summarize_paper(
        _pub(), llm=llm, style="B", voice_profile="Crisp, active voice.",
        context="A CNN improves accuracy.",
    )
    user = llm.calls[0]["user"]
    assert STYLES["B"] in user  # audience style still present
    assert "Crisp, active voice." in user  # voice profile also present


# --------------------------------------------------------------------------- #
# sanitize_summary
# --------------------------------------------------------------------------- #
def test_sanitize_em_dash_to_comma():
    assert sanitize_summary("A — B") == "A, B"


def test_sanitize_en_dash_range_to_hyphen():
    assert sanitize_summary("pages 10–20 here") == "pages 10-20 here"


def test_sanitize_other_en_dash_to_comma():
    assert sanitize_summary("cats – dogs") == "cats, dogs"


def test_sanitize_unspaced_en_dash_in_compound_becomes_hyphen():
    # Regression: the fallback rule used to turn every remaining en dash into a
    # comma, so a compound word came back as a comma splice ("tongue, jaw").
    assert sanitize_summary("tongue–jaw coordination") == "tongue-jaw coordination"


def test_sanitize_unspaced_en_dash_in_name_pair_becomes_hyphen():
    assert sanitize_summary("the Fels–Pai model") == "the Fels-Pai model"


def test_sanitize_distinguishes_spaced_from_unspaced_en_dash():
    out = sanitize_summary("The tongue–jaw linkage – the core idea – is measured.")
    assert out == "The tongue-jaw linkage, the core idea, is measured."


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


def test_evaluate_flags_by_gerund_connective():
    # The most common tell in the live corpus: 70 of 72 sampled summaries.
    ev = evaluate_summary(
        "By combining ultrasound with a biomechanical model, the system tracks tongue motion.",
        _pub(),
    )
    assert ev.gerund_connective is True
    assert "B" in ev.flags
    assert ev.clean is False


def test_evaluate_flags_by_gerund_mid_text():
    ev = evaluate_summary(
        "A biomechanical model tracks tongue motion. By training on paired scans, "
        "it generalizes to unseen speakers.",
        _pub(),
    )
    assert ev.gerund_connective is True


def test_evaluate_lowercase_by_gerund_is_not_flagged():
    # "by combining" mid-sentence is ordinary English, not the stock connective.
    ev = evaluate_summary(
        "Tongue motion is recovered by combining ultrasound with a biomechanical model.",
        _pub(),
    )
    assert ev.gerund_connective is False


def test_evaluate_flags_formulaic_closer():
    ev = evaluate_summary(
        "Ultrasound and a biomechanical model together recover tongue motion. "
        "This work helps researchers understand speech production.",
        _pub(),
    )
    assert ev.formulaic_closer is True
    assert "C" in ev.flags
    assert ev.clean is False


def test_evaluate_flags_helps_audience_closer():
    ev = evaluate_summary(
        "A multi-scale segmentation model recovers paraspinal muscle geometry, which "
        "helps surgeons plan corrective procedures.",
        _pub(),
    )
    assert ev.formulaic_closer is True


def test_evaluate_concrete_provides_is_not_a_formulaic_closer():
    ev = evaluate_summary(
        "The finite-difference solver provides a closed-form update for each mesh node.",
        _pub(),
    )
    assert ev.formulaic_closer is False


# --- shape-based filler openers -------------------------------------------- #
def test_evaluate_flags_shape_variant_filler_openers():
    # None of these match any literal entry in the prefix list.
    for s in (
        "This project introduces a new segmentation pipeline for upright MRI scans.",
        "The system reconstructs airway geometry from a handful of sparse scans.",
        "Researchers created a haptic controller for bimanual selection tasks.",
        "Researchers used a paired-scan dataset to fit the deformation model.",
        "Research shows that bimanual input reduces selection time in modeling tasks.",
    ):
        assert evaluate_summary(s, _pub()).filler_opening is True, s


def test_evaluate_does_not_flag_genuine_subject_first_openers():
    for s in (
        "Vocal tract reconstruction from real-time MRI gains a new deep-learning front end.",
        "A tongue model driven by muscle activation reproduces observed swallow kinematics.",
        "Two haptic controllers are compared under identical task loads and timings.",
        "Bimanual input reduces selection time in a three-dimensional modeling task.",
        "Researchers at three sites contributed the paired-scan dataset used here.",
    ):
        assert evaluate_summary(s, _pub()).filler_opening is False, s


def test_evaluate_first_person_opener_is_filler_without_a_voice_profile():
    s = "We build a segmentation pipeline that recovers muscle geometry from upright MRI."
    assert evaluate_summary(s, _pub()).filler_opening is True


def test_evaluate_first_person_opener_allowed_with_a_voice_profile():
    # A voice profile that asks for first-person plural must not then be scored
    # as a house-style violation for using it.
    s = "We build a segmentation pipeline that recovers muscle geometry from upright MRI."
    ev = evaluate_summary(s, _pub(), voice_profile="First person plural; we build things.")
    assert ev.filler_opening is False
    assert ev.clean is True


def test_evaluate_voice_profile_does_not_excuse_other_filler_openers():
    ev = evaluate_summary(
        "This paper presents a segmentation pipeline for upright MRI scans of the spine.",
        _pub(),
        voice_profile="First person plural; we build things.",
    )
    assert ev.filler_opening is True


def test_evaluate_blank_voice_profile_keeps_first_person_check():
    s = "We build a segmentation pipeline that recovers muscle geometry from upright MRI."
    assert evaluate_summary(s, _pub(), voice_profile="   ").filler_opening is True


def test_evaluate_thousands_separator_not_ungrounded():
    # "10,000" in the summary must match "10000" in the source (no spurious "000").
    ev = evaluate_summary(
        "The review screened over 10,000 records across many databases and sources here.",
        _pub(),
        source_text="we screened 10000 records",
    )
    assert ev.ungrounded_numbers == []
