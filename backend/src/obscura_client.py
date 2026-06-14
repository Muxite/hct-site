"""Render a page to text via the obscura headless browser (binary mode).

ujin's ``links``/``article`` extractors discard a Google Scholar profile's
authors/venue/year text, and the per-paper pages are bot-walled — but obscura
*rendering the profile* captures the whole table. ``obscura fetch <url> --dump
text`` returns that as plain text, which the normal LLM extractor parses into
grounded publications (verified: 92 papers for Fels, real metadata, no
hallucination).

This is deliberately a thin subprocess wrapper around the same binary ujin
bundles (``obscura fetch``), so it stays a black box: we shell out, get text,
and hand it to ``extract_publications``. The subprocess runner is injectable so
tests never spawn a real browser.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

#: (argv, timeout_secs) -> (returncode, stdout_text). Injected for tests.
Runner = Callable[[list[str], float], "tuple[int, str]"]


class ObscuraError(RuntimeError):
    """Raised when obscura is unavailable or returns no usable text."""


class BlockedError(ObscuraError):
    """Raised when the rendered page is an anti-bot / CAPTCHA interstitial."""


# Markers of a Google "unusual traffic" / CAPTCHA wall (vs. a real page).
_BLOCK_MARKERS = (
    "unusual traffic",
    "not a robot",
    "detected unusual",
    "solving the above captcha",
    "enable javascript on your web browser",
)


def looks_blocked(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _BLOCK_MARKERS)


def _subprocess_runner(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - real-process only
        raise ObscuraError(f"obscura timed out after {timeout}s: {' '.join(argv)}") from exc
    except FileNotFoundError as exc:
        raise ObscuraError(f"obscura binary not found: {argv[0]!r}") from exc
    return proc.returncode, proc.stdout or ""


class ObscuraRenderer:
    """Headless render → plain text via the obscura binary.

    ``bin`` is the binary path/name (default ``obscura``; the backend image bakes
    it in from the ujin-full build). ``min_chars`` guards against a block/consent
    page being passed downstream as if it were real content.
    """

    def __init__(
        self,
        bin: str = "obscura",
        *,
        wait: int = 6,
        timeout: int = 40,
        stealth: bool = True,
        min_chars: int = 500,
        runner: Runner | None = None,
    ) -> None:
        self.bin = bin
        self.wait = wait
        self.timeout = timeout
        self.stealth = stealth
        self.min_chars = min_chars
        self._run = runner or _subprocess_runner

    def available(self) -> bool:
        """True if the obscura binary can be found (path or on PATH)."""

        return Path(self.bin).is_file() or shutil.which(self.bin) is not None

    def render_text(self, url: str, *, selector: str | None = None) -> str:
        """Render ``url`` and return its visible text. Raises :class:`ObscuraError`.

        ``selector`` scopes the dump to one element (e.g. Scholar's ``#gsc_a_b``
        table body), dropping page chrome so the LLM sees only the rows.
        """

        argv = [
            self.bin, "fetch", url,
            "--dump", "text",
            "--wait", str(self.wait),
            "--timeout", str(self.timeout),
        ]
        if selector:
            argv += ["--selector", selector]
        if self.stealth:
            argv.append("--stealth")

        code, out = self._run(argv, self.timeout + 10)
        if code != 0:
            raise ObscuraError(f"obscura exited {code} rendering {url}")
        text = (out or "").strip()
        if looks_blocked(text):
            raise BlockedError(
                f"anti-bot/CAPTCHA wall rendering {url} "
                "(Google detected unusual traffic — back off and retry later)"
            )
        if len(text) < self.min_chars:
            raise ObscuraError(
                f"obscura returned only {len(text)} chars for {url} "
                "(likely a block/consent page, not the profile)"
            )
        return text
