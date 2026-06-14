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
    "prescriptive style profile (tone, sentence structure, vocabulary, voice, "
    "formatting). Output plain text only, ~150 words max."
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


def analyze_style(
    text: str,
    *,
    llm: SupportsComplete,
    system_prompt: str | None = None,
    max_chars: int = 12000,
) -> str:
    """Produce a short style profile for ``text`` using the LLM (free text)."""

    if not text or not text.strip():
        raise ValueError("cannot analyze empty text")
    system = system_prompt if system_prompt is not None else _DEFAULT_STYLE_SYSTEM
    snippet = text.strip()[:max_chars]
    profile = llm.complete(
        system=system,
        user=f"Document to analyze:\n\n{snippet}",
        json_mode=False,
        max_tokens=400,
        label="style",
    )
    return profile.strip()
