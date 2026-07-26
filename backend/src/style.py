"""Style analysis: read an input document and produce a short style profile.

The profile (free text) is fed into the extraction/generation prompt so any
LLM-written descriptions match the lab's voice. The document reader is
dependency-free: ``.docx`` is unzipped and its text pulled from the XML;
``.txt/.md/.tex`` and unknown text files are read as plain UTF-8.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Protocol

_DEFAULT_STYLE_SYSTEM = (
    "Analyze the writing style of the document and produce a short but detailed, "
    "prescriptive style profile. Describe voice only: tone and register, "
    "diction and vocabulary, sentence rhythm and structure, and the writer's "
    "stance toward the reader. Do NOT describe layout, headings, bullets, "
    "bolding, markdown, section structure, or length; those are set separately "
    "by the requested output style, and a profile that prescribes them will "
    "fight it. Output the profile text only, with no preamble, no headers, and "
    "no commentary. Plain text only, ~150 words max."
)

# A profile is free text, so there is no schema to validate against, but two
# failure modes are cheap to catch before the text is stored and then pasted
# into every downstream prompt: a chat-style preamble, and a response that
# blew past the ~150-word target (usually the model restating the document).
_PREAMBLE_RE = re.compile(
    r"^\s*(?:sure\b|certainly\b|of course\b|okay\b|ok\b|absolutely\b"
    r"|here(?:'s| is| are)\b|below is\b|i(?:'ve| have)\b"
    r"|(?:the\s+)?(?:style\s+)?profile\s*:)",
    re.IGNORECASE,
)
_PROFILE_MAX_WORDS = 300  # 2x the ~150-word target; only catches runaways
_RETRY_NUDGE = (
    "\n\nIMPORTANT: your previous answer was rejected. Reply with the profile "
    "text itself and nothing else: no preamble, no lead-in sentence, no "
    "headers, and no more than 150 words."
)


class SupportsComplete(Protocol):
    def complete(self, *, system: str, user: str, **kw: Any) -> str: ...


def _read_docx(path: Path) -> str:
    """Extract visible text from a .docx (word/document.xml <w:t> runs)."""

    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    # One output line per paragraph: split on </w:p> and join each paragraph's
    # text runs. (Substituting "\n" into the XML doesn't work — the newline
    # lands *between* <w:t> elements and is dropped by the run regex.)
    # NB: require whitespace (or nothing) after "w:t" so <w:tab/> does not match
    # as an opening tag — on tab-heavy documents (e.g. the UBC CV form) that bug
    # swallowed everything up to the next real </w:t> and leaked raw XML.
    lines = []
    for para in xml.split("</w:p>"):
        runs = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", para, flags=re.DOTALL)
        if runs:
            lines.append("".join(runs))
    text = "\n".join(lines)
    # Unescape the handful of XML entities Word emits.
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(ent, ch)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_text_input(path: str | Path) -> str:
    """Read text from a supported input document."""

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".docx":
        return _read_docx(path)
    # .txt/.md/.tex/anything else: treat as plain text.
    return path.read_text(encoding="utf-8", errors="replace").strip()


def load_style_system_prompt(templates_dir: str | Path | None) -> str:
    if templates_dir:
        p = Path(templates_dir) / "style_system.txt"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return _DEFAULT_STYLE_SYSTEM


def strip_profile_preamble(text: str) -> str:
    """Drop a chat-style lead-in ("Here is the style profile:") from ``text``."""

    t = (text or "").strip()
    if not t or not _PREAMBLE_RE.match(t):
        return t
    lines = t.splitlines()
    first = lines[0].strip()
    # A short preamble on its own line: drop the line.
    if len(lines) > 1 and len(first.split()) <= 20:
        return "\n".join(lines[1:]).strip()
    # Or an inline one: "Here is the profile: Tone is formal, ...".
    head, sep, rest = t.partition(":")
    if sep and rest.strip() and len(head.split()) <= 20:
        return rest.strip()
    return t


def check_profile(text: str) -> str:
    """Return why ``text`` is unusable as a style profile, or "" if it looks fine."""

    t = (text or "").strip()
    if not t:
        return "empty response"
    if _PREAMBLE_RE.match(t):
        return "starts with a preamble instead of the profile"
    n = len(t.split())
    if n > _PROFILE_MAX_WORDS:
        return f"{n} words, far over the ~150-word target"
    return ""


def analyze_style(
    text: str,
    *,
    llm: SupportsComplete,
    system_prompt: str | None = None,
    max_chars: int = 12000,
) -> str:
    """Produce a short style profile for ``text`` using the LLM (free text).

    The profile is free prose, so there is no Pydantic model to validate it
    against, but it is stored and then prepended to every downstream generation
    prompt, so an obviously malformed response must not get that far. The
    response is preamble-stripped and sanity-checked; a failure buys one repair
    retry (the project's usual pattern), and a second failure raises.
    """

    if not text or not text.strip():
        raise ValueError("cannot analyze empty text")
    system = system_prompt if system_prompt is not None else _DEFAULT_STYLE_SYSTEM
    snippet = text.strip()[:max_chars]
    user = f"Document to analyze:\n\n{snippet}"

    profile = strip_profile_preamble(
        llm.complete(
            system=system, user=user, json_mode=False, max_tokens=400, label="style"
        )
    )
    problem = check_profile(profile)
    if not problem:
        return profile

    profile = strip_profile_preamble(
        llm.complete(
            system=system + _RETRY_NUDGE,
            user=user,
            json_mode=False,
            max_tokens=400,
            label="style-repair",
        )
    )
    problem = check_profile(profile)
    if problem:
        raise ValueError(f"style profile looks malformed after one retry: {problem}")
    return profile
