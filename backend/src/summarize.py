"""Write a brief, digestible overview of one paper, in a chosen writing style.

This is the generation core for the paper-summary bake-off. It reuses the
grounded discipline of ``describe.py`` (write only from the provided source text,
never invent numbers or claims) but is built for *experimentation*: five named
writing styles (A-E) and a hard house style that bans em dashes and emojis, so we
can compare approaches side by side on the sample page.

The style is injected the same way ``describe`` injects a lab voice: as a short
prescriptive profile prepended to the prompt. ``summarize_paper`` returns the
sanitized text; ``evaluate_summary`` runs the cheap automated quality checks used
by the harness report (mirrors ``experiments/describe_eval``, plus em-dash/emoji).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.models import Publication

STYLES: dict[str, str] = {
    "A": (
        "Plain-language explainer for a curious non-specialist. Say what the work "
        "is and why it was done in everyday words, defining any necessary term in "
        "passing. One short paragraph, roughly 60 to 90 words. Calm and clear, no hype."
    ),
    "B": (
        "Condensed technical abstract for peers in the field. Use precise domain "
        "terminology and state the contribution and approach compactly. One "
        "paragraph, roughly 70 to 100 words. Assume the reader knows the basics."
    ),
    "C": (
        "Three short labeled beats in markdown: a bold 'Problem:', a bold "
        "'Approach:', and a bold 'Result:'. One or two sentences each. Stay "
        "concrete and factual."
    ),
    "D": (
        "Significance-first. Lead with why the work matters and who benefits, then "
        "briefly how it was achieved. One short paragraph, roughly 60 to 90 words. "
        "Motivate before mechanism."
    ),
    "E": (
        "Two question-and-answer pairs in markdown. Bold the questions 'What "
        "problem does this address?' and 'What did the authors do?'; answer each in "
        "one or two sentences."
    ),
}

SUMMARY_SYSTEM = (
    "You write a brief, digestible overview of one academic paper for its page on "
    "a research lab's website. Ground every statement in the provided source text "
    "and metadata; never invent results, numbers, methods, or claims that are not "
    "supported by what you are given. House style: technical but readable; do not "
    "use em dashes or en dashes; do not use emojis; do not repeat the paper's "
    "title back; do not start with filler like 'This paper' or 'In this work'. "
    "Follow the requested writing style exactly."
)

# Emoji + pictographic blocks (symbols/dingbats, stars/misc-symbols, flags) plus
# the variation selector / zero-width joiner / keycap that compose emoji. Arrows
# (U+2190-21FF) are deliberately left in - they are not emoji.
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U00002b00-\U00002bff\U0001f1e6-\U0001f1ff]"
    "|[️‍⃣]"
)
_FILLER_OPENERS = (
    "this paper", "in this paper", "this study", "this work", "the paper",
    "this research", "this article", "in this work", "we ",
)
_SENT_SPLIT = re.compile(r"[.!?]+(?:\s|$)")

# First-person openers are only filler when the lab has *not* asked for a
# first-person voice. ``evaluate_summary(..., voice_profile=...)`` exempts them:
# a voice profile that says "we build things" would otherwise be flagged for
# obeying itself.
_FIRST_PERSON_OPENERS = ("we ",)

# Shape-based filler openers, to catch the variants a literal prefix list keeps
# missing ("this project introduces", "researchers created a", "research
# shows"). Deliberately narrow: only the stock "this/the <generic noun>" frame
# and a "researchers <verb>" lead, and the latter skips prepositional follow-ons
# ("Researchers at UBC ...") so a genuine subject-first opener is not flagged.
_FILLER_OPENER_RE = re.compile(
    r"^(?:in\s+)?(?:this|the)\s+"
    r"(?:paper|study|work|research|article|project|system|framework|review)\b"
    r"|^research(?:ers)?\s+"
    r"(?!at\b|from\b|in\b|into\b|of\b|on\b|and\b|about\b|who\b|with\b|whose\b)\w+",
    re.IGNORECASE,
)

# "By <gerund>, ..." at the start of a sentence: the single most common stock
# connective in the generated corpus (70 of 72 sampled summaries used it).
_GERUND_CONNECTIVE_RE = re.compile(r"(?:^|[.!?]\s+|\n)By \w+ing\b")

# The formulaic closer family the house style already bans in prose but nothing
# checked for: "this work helps ...", "this tool aims to ...", "helps
# researchers understand ...".
_FORMULAIC_CLOSER_RE = re.compile(
    r"\bthis\s+(?:work|research|project|tool)\s+"
    r"(?:helps?|aims?\s+to|provides?|enables?|offers?)\b"
    r"|\bhelps?\s+"
    r"(?:researchers|scientists|doctors|surgeons|clinicians|experts|practitioners)\b",
    re.IGNORECASE,
)


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


def resolve_style(style: str) -> str:
    """Accept a style key ('A'..'H') or a literal profile string; return the profile."""

    return STYLES.get(style, style)


def sanitize_summary(text: str) -> str:
    """Enforce the house style on generated text: no em/en dashes, no emojis.

    Em dashes become commas. En dashes are read by *spacing*, because the two
    uses are different punctuation: an **unspaced** en dash joins a compound or
    a name pair ("tongue-jaw", "Fels-Pai") and becomes a plain hyphen, while a
    **spaced** en dash is a sentence-level break and becomes a comma. Digit
    ranges ("10-20") are hyphenated whether spaced or not. Emojis are stripped.
    Markdown structure (bullets, line breaks) is preserved so bulleted styles
    still render.
    """

    text = re.sub(r"\s*—\s*", ", ", text)  # em dash -> comma
    text = re.sub(r"(?<=\d)\s*–\s*(?=\d)", "-", text)  # en dash range -> hyphen
    text = re.sub(r"(?<=\w)–(?=\w)", "-", text)  # compound / name pair -> hyphen
    text = re.sub(r"\s*–\s*", ", ", text)  # sentence-break en dash -> comma
    text = _EMOJI.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +([,.;:])", r"\1", text)
    return text.strip()


def build_summary_prompt(
    pub: Publication, *, style_profile: str, voice_profile: str = "", context: str = ""
) -> str:
    """Build the user prompt for one paper + style + grounding context.

    ``style_profile`` is the audience-facing writing style (a :data:`STYLES`
    key's text or a literal profile, e.g. "three labeled beats") - what shape
    the overview takes. ``voice_profile`` is a separate, optional lab-voice
    calibration block (``style_profile.profile_text`` from the admin's pasted
    exemplar, see ``src/style.py``/``hct-manager style-regen``) - how the lab
    sounds. The two are independent prompt blocks; supplying one never alters
    or overwrites the other's instruction. The voice block carries an explicit
    precedence rule, because without one a voice profile will happily override
    the style's length and shape constraints.
    """

    parts: list[str] = [f"Write the overview in this style:\n{style_profile.strip()}\n"]
    if voice_profile.strip():
        parts.append(
            "Match this lab's writing voice in diction, rhythm, and stance:\n"
            f"{voice_profile.strip()}\n"
            "Where that voice conflicts with the requested style's shape, length, "
            "or grounding rules, the style and the grounding rules win.\n"
        )
    facts = [
        f"Title: {pub.title}",
        f"Authors: {'; '.join(pub.authors)}",
        f"Year: {pub.year}",
    ]
    if pub.venue:
        facts.append(f"Venue: {pub.venue}")
    parts.append("Paper:\n" + "\n".join(facts))
    if context.strip():
        parts.append(
            "\nSource text from the paper (use only this for facts):\n" + context.strip()
        )
    else:
        parts.append("\n(No source text available. Stay general and do not invent specifics.)")
    parts.append("\nWrite the overview now.")
    return "\n".join(parts)


def summarize_paper(
    pub: Publication,
    *,
    llm: SupportsComplete,
    style: str,
    voice_profile: str = "",
    context: str = "",
    system_prompt: str | None = None,
    max_tokens: int = 400,
    label: str = "summary",
) -> str:
    """Generate one sanitized overview of ``pub`` in ``style`` from ``context``.

    ``style`` is a key in :data:`STYLES` (or a literal profile). ``voice_profile``
    is the separate, optional lab-voice calibration text (see
    :func:`build_summary_prompt`) - distinct from ``style``, which only picks
    the audience-facing shape. Output is capped low - these are brief overviews
    - and run through :func:`sanitize_summary`.
    """

    system = system_prompt if system_prompt is not None else SUMMARY_SYSTEM
    user = build_summary_prompt(
        pub, style_profile=resolve_style(style), voice_profile=voice_profile, context=context
    )
    raw = llm.complete(
        system=system, user=user, json_mode=False, max_tokens=max_tokens, label=label
    )
    return sanitize_summary(raw)


# --------------------------------------------------------------------------- #
# Automated quality checks (for the harness report)
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _numbers(s: str) -> set[str]:
    # Strip thousands separators first so "10,000" / "10 000" compare equal to
    # "10000" (otherwise the check spuriously flags "000" as ungrounded).
    s = re.sub(r"(?<=\d)[,  ](?=\d{3}(?!\d))", "", s or "")
    return set(re.findall(r"(?<![\w-])\d+(?:\.\d+)?(?![\w])", s))


@dataclass
class SummaryEval:
    """Cheap automated flags for one generated summary."""

    n_words: int
    n_sentences: int
    has_em_dash: bool
    has_emoji: bool
    too_long: bool  # > 140 words or > 8 sentences
    too_short: bool  # < 12 words
    repeats_title: bool
    filler_opening: bool
    gerund_connective: bool = False  # "By combining X, ..." sentence opener
    formulaic_closer: bool = False  # "this work helps researchers ..."
    ungrounded_numbers: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (
            self.has_em_dash
            or self.has_emoji
            or self.too_long
            or self.too_short
            or self.repeats_title
            or self.filler_opening
            or self.gerund_connective
            or self.formulaic_closer
            or self.ungrounded_numbers
        )

    @property
    def flags(self) -> str:
        return "".join([
            "M" if self.has_em_dash else "",
            "E" if self.has_emoji else "",
            "L" if self.too_long else "",
            "S" if self.too_short else "",
            "T" if self.repeats_title else "",
            "F" if self.filler_opening else "",
            "B" if self.gerund_connective else "",
            "C" if self.formulaic_closer else "",
            "N" if self.ungrounded_numbers else "",
        ]) or "ok"


def _filler_opening(ndesc: str, *, allow_first_person: bool = False) -> bool:
    """True when ``ndesc`` (normalized) starts with a stock, templated opener.

    Two checks: the literal prefix list, and the shape regex that catches the
    same frames with different nouns/verbs. ``allow_first_person`` drops "we "
    from the literal list, for the case where the lab's voice profile explicitly
    asks for first-person plural.
    """

    openers = _FILLER_OPENERS
    if allow_first_person:
        openers = tuple(o for o in openers if o not in _FIRST_PERSON_OPENERS)
    return ndesc.startswith(openers) or bool(_FILLER_OPENER_RE.match(ndesc))


def evaluate_summary(
    summary: str, pub: Publication, *, source_text: str = "", voice_profile: str = ""
) -> SummaryEval:
    """Score one summary against the house style and its grounding source.

    ``voice_profile`` is the lab-voice calibration text the summary was written
    under (see :func:`build_summary_prompt`). When one is supplied, first-person
    openers stop counting as filler: a profile that asks for "we" should not
    then be marked as violating the house style for using it.
    """

    summary = (summary or "").strip()
    words = re.findall(r"\b\w+\b", summary)
    sentences = [s for s in _SENT_SPLIT.split(summary) if s.strip()]
    ndesc = _norm(summary)
    ntitle = _norm(pub.title)
    meta = _norm(" ".join([pub.title, "; ".join(pub.authors), str(pub.year), pub.venue or ""]))
    grounded_numbers = _numbers(source_text) | _numbers(meta) | {str(pub.year)}
    return SummaryEval(
        n_words=len(words),
        n_sentences=len(sentences),
        has_em_dash=bool(re.search(r"[—–]", summary)),
        has_emoji=bool(_EMOJI.search(summary)),
        too_long=(len(words) > 140 or len(sentences) > 8),
        too_short=(len(words) < 12),
        repeats_title=(len(ntitle) > 12 and ntitle in ndesc),
        filler_opening=_filler_opening(
            ndesc, allow_first_person=bool(voice_profile.strip())
        ),
        gerund_connective=bool(_GERUND_CONNECTIVE_RE.search(summary)),
        formulaic_closer=bool(_FORMULAIC_CLOSER_RE.search(summary)),
        ungrounded_numbers=sorted(_numbers(summary) - grounded_numbers),
    )
