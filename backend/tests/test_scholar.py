"""Tests for the Google Scholar URL/mode helpers."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from src import scholar

PROFILE = "https://scholar.google.com/citations?user=bf7ilxMAAAAJ&hl=en&oi=ao"
PER_PAPER = (
    "https://scholar.google.com/citations?view_op=view_citation&hl=en"
    "&user=bf7ilxMAAAAJ&citation_for_view=bf7ilxMAAAAJ:9Nmd_mFXekoC"
)


@pytest.mark.parametrize(
    "url,expected",
    [
        (PROFILE, True),
        ("https://scholar.google.de/citations?user=abc", True),
        (PER_PAPER, False),  # has citation_for_view -> a single paper, not the profile
        ("https://scholar.google.com/citations?hl=en", False),  # no user id
        ("https://example.com/citations?user=x", False),  # not scholar
    ],
)
def test_is_scholar_profile(url: str, expected: bool) -> None:
    assert scholar.is_scholar_profile(url) is expected


def test_normalize_sets_pagesize_hl_and_pubdate_sort() -> None:
    out = scholar.normalize_profile_url(PROFILE, pagesize=100)
    q = parse_qs(urlparse(out).query)
    assert q["pagesize"] == ["100"]
    assert q["hl"] == ["en"]
    assert q["sortby"] == ["pubdate"]       # newest-first
    assert q["view_op"] == ["list_works"]
    assert q["user"] == ["bf7ilxMAAAAJ"]  # preserved


def test_normalize_is_idempotent_and_overrides_existing_pagesize() -> None:
    once = scholar.normalize_profile_url(PROFILE + "&pagesize=20")
    twice = scholar.normalize_profile_url(once)
    assert once == twice
    assert parse_qs(urlparse(twice).query)["pagesize"] == ["100"]


def test_normalize_leaves_non_profile_urls_untouched() -> None:
    assert scholar.normalize_profile_url(PER_PAPER) == PER_PAPER
    assert scholar.normalize_profile_url("https://example.com/x") == "https://example.com/x"


def test_scrape_mode_for() -> None:
    assert scholar.scrape_mode_for(PROFILE, fallback="article") == "links"
    assert scholar.scrape_mode_for(PER_PAPER, fallback="article") == "article"
    assert scholar.scrape_mode_for("https://example.com", fallback="auto") == "auto"
