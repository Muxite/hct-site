"""Unit tests for the paper-sample orchestrator (all collaborators faked)."""

from __future__ import annotations

import re

import pytest

from src.metrics import UsageTracker
from src.models import Publication
from src.paper_samples import (
    PaperBundle,
    build_paper_samples,
    fetch_source_text,
    sample_row,
)
from src.paper_sources import LinkResult, WorkRecord


def _pub(slug="zhu2022-x", title="A unified representation of control logic") -> Publication:
    return Publication(id=slug, title=title, authors=["Hongzhi Zhu"], year=2022, venue="J. Ex")


def _link(**kw) -> LinkResult:
    base = dict(
        canonical_url="https://doi.org/10.1234/abc",
        oa_url="https://oa.example/paper.pdf",
        abstract="We study control logic and report an approach.",
        confidence=0.95,
        matched=True,
        reason="known DOI (trusted)",
        record=WorkRecord(source="openalex", title="A unified representation of control logic"),
    )
    base.update(kw)
    return LinkResult(**base)


class FakeSources:
    def __init__(self, link: LinkResult) -> None:
        self.link = link
        self.seen: list[tuple[str, str | None]] = []

    def discover(self, *, title, authors, year, doi=None) -> LinkResult:
        self.seen.append((title, doi))
        return self.link


class FakeLLM:
    tracker = None

    def __init__(self, reply: str = "A grounded overview with plenty of words to clear the short check here today.") -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, *, system, user, **kw) -> str:
        self.calls += 1
        if self.tracker is not None:
            self.tracker.record(
                model="fake", usage={"prompt_tokens": 10, "completion_tokens": 5}, latency_s=0.01
            )
        return self.reply


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * 32
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                v[hash(tok) % 32] += 1.0
            out.append(v)
        return out


# --------------------------------------------------------------------------- #
# fetch_source_text
# --------------------------------------------------------------------------- #
def test_fetch_uses_full_text_when_substantial():
    body = "Full body. " * 60  # > 400 chars
    text, used = fetch_source_text(_link(), fetch=lambda url: body)
    assert used is True
    assert "We study control logic" in text  # abstract kept on top
    assert "Full body." in text


def test_fetch_falls_back_to_abstract_when_fetch_short():
    text, used = fetch_source_text(_link(), fetch=lambda url: "tiny")
    assert used is False
    assert text == "We study control logic and report an approach."


def test_fetch_handles_fetch_error():
    def boom(url):
        raise RuntimeError("network down")

    text, used = fetch_source_text(_link(), fetch=boom)
    assert used is False
    assert text.startswith("We study")


def test_fetch_no_fetch_callable():
    text, used = fetch_source_text(_link(), fetch=None)
    assert used is False
    assert text.startswith("We study")


def test_fetch_prefers_fulltext_by_doi():
    body = "PMC full body text. " * 60  # > 400 chars

    # fulltext_by_doi resolves from the DOI; the URL fetch should be skipped.
    def fetch(url):  # pragma: no cover - must not be called
        raise AssertionError("fetch should not run when fulltext_by_doi succeeds")

    text, used = fetch_source_text(_link(), fetch=fetch, fulltext_by_doi=lambda doi: body)
    assert used is True
    assert "PMC full body" in text


def test_fetch_falls_back_to_url_when_fulltext_empty():
    body = "fetched url body. " * 60

    text, used = fetch_source_text(
        _link(), fetch=lambda url: body, fulltext_by_doi=lambda doi: ""
    )
    assert used is True
    assert "fetched url body" in text


# --------------------------------------------------------------------------- #
# build_paper_samples
# --------------------------------------------------------------------------- #
def test_matrix_shape_and_positions():
    llm = FakeLLM()
    llm.tracker = UsageTracker()  # mark it as a tracker-carrying client
    bundles = build_paper_samples(
        [_pub()],
        sources=FakeSources(_link()),
        llm=llm,
        fetch=lambda url: "Full body text. " * 60,
        embedder=FakeEmbedder(),
        styles=("A", "B"),
        modes=("rag", "full"),
        model="fake-model",
    )
    assert len(bundles) == 1
    samples = bundles[0].samples
    assert len(samples) == 4  # 2 styles x 2 modes
    assert {(s.style, s.mode) for s in samples} == {("A", "rag"), ("A", "full"), ("B", "rag"), ("B", "full")}
    assert [s.position for s in samples] == [0, 1, 2, 3]
    assert llm.calls == 4


def test_samples_carry_link_and_isolated_tokens():
    llm = FakeLLM()
    llm.tracker = UsageTracker()
    bundles = build_paper_samples(
        [_pub()],
        sources=FakeSources(_link(confidence=0.91)),
        llm=llm,
        fetch=lambda url: "Full body text. " * 60,
        embedder=FakeEmbedder(),
        styles=("A",),
        modes=("full",),
        model="fake-model",
    )
    s = bundles[0].samples[0]
    assert s.link == "https://doi.org/10.1234/abc"
    assert s.oa_url == "https://oa.example/paper.pdf"
    assert s.confidence == 0.91
    assert s.model == "fake-model"
    # Per-call token isolation: one call -> 10 prompt / 5 completion, not accumulated.
    assert s.prompt_tokens == 10 and s.completion_tokens == 5


def test_rag_context_smaller_than_full():
    llm = FakeLLM()
    bundles = build_paper_samples(
        [_pub()],
        sources=FakeSources(_link()),
        llm=llm,
        fetch=lambda url: "The method trains a model. " * 80,
        embedder=FakeEmbedder(),
        styles=("A",),
        modes=("rag", "full"),
        model="m",
        rag_max_chars=300,
    )
    by_mode = {s.mode: s for s in bundles[0].samples}
    assert by_mode["rag"].source_chars <= by_mode["full"].source_chars


def test_rag_mode_requires_embedder():
    with pytest.raises(ValueError):
        build_paper_samples(
            [_pub()],
            sources=FakeSources(_link()),
            llm=FakeLLM(),
            embedder=None,
            modes=("rag",),
        )


def test_full_only_mode_needs_no_embedder():
    bundles = build_paper_samples(
        [_pub()],
        sources=FakeSources(_link()),
        llm=FakeLLM(),
        embedder=None,
        styles=("A",),
        modes=("full",),
    )
    assert isinstance(bundles[0], PaperBundle)
    assert len(bundles[0].samples) == 1


def test_sample_row_has_db_columns_only():
    llm = FakeLLM()
    bundles = build_paper_samples(
        [_pub()],
        sources=FakeSources(_link()),
        llm=llm,
        embedder=None,
        styles=("A",),
        modes=("full",),
        model="m",
    )
    row = sample_row(bundles[0].samples[0])
    assert set(row) == {
        "paper_slug", "style", "mode", "model", "summary",
        "link", "oa_url", "confidence", "prompt_tokens", "completion_tokens",
        "latency_s", "position",
    }
    assert "evaluation" not in row and "title" not in row
