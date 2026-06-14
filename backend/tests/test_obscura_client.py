"""Tests for the obscura renderer wrapper (no real browser is ever spawned)."""

from __future__ import annotations

import pytest

from src.obscura_client import BlockedError, ObscuraError, ObscuraRenderer, looks_blocked


def _runner(returncode: int, stdout: str, *, capture: list | None = None):
    def run(argv, timeout):
        if capture is not None:
            capture.append((argv, timeout))
        return returncode, stdout
    return run


def test_render_text_returns_stdout_on_success() -> None:
    text = "x" * 1000
    r = ObscuraRenderer("obscura", runner=_runner(0, "  " + text + "  "))
    assert r.render_text("https://scholar.google.com/citations?user=A") == text


def test_render_text_builds_expected_argv() -> None:
    captured: list = []
    r = ObscuraRenderer("obscura", wait=7, timeout=30, runner=_runner(0, "y" * 800, capture=captured))
    r.render_text("https://example.com/p")
    argv, timeout = captured[0]
    assert argv[:3] == ["obscura", "fetch", "https://example.com/p"]
    assert "--dump" in argv and argv[argv.index("--dump") + 1] == "text"
    assert "--stealth" in argv
    assert argv[argv.index("--wait") + 1] == "7"
    assert argv[argv.index("--timeout") + 1] == "30"
    assert timeout == 40  # timeout + 10 grace


def test_no_stealth_when_disabled() -> None:
    captured: list = []
    r = ObscuraRenderer("obscura", stealth=False, runner=_runner(0, "z" * 800, capture=captured))
    r.render_text("https://example.com")
    assert "--stealth" not in captured[0][0]


def test_render_text_raises_on_nonzero_exit() -> None:
    r = ObscuraRenderer("obscura", runner=_runner(1, ""))
    with pytest.raises(ObscuraError, match="exited 1"):
        r.render_text("https://example.com")


def test_render_text_raises_on_too_little_text() -> None:
    # A consent/block page is short — guard against passing it downstream.
    r = ObscuraRenderer("obscura", min_chars=500, runner=_runner(0, "Please verify you are human"))
    with pytest.raises(ObscuraError, match="block/consent"):
        r.render_text("https://scholar.google.com/citations?user=A")


def test_detects_captcha_block_page() -> None:
    block = ("Our systems have detected unusual traffic from your computer network. "
             "This page checks to see if it's really you sending the requests, and not a robot.")
    assert looks_blocked(block) is True
    assert looks_blocked("a normal page about publications") is False
    r = ObscuraRenderer("obscura", min_chars=10, runner=_runner(0, block))
    with pytest.raises(BlockedError):
        r.render_text("https://scholar.google.com/citations?user=A")


def test_available(tmp_path) -> None:
    real = tmp_path / "obscura"
    real.write_text("#!/bin/sh\n")
    assert ObscuraRenderer(str(real)).available() is True
    assert ObscuraRenderer(str(tmp_path / "nope-not-here")).available() is False
