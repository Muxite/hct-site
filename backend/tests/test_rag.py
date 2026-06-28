"""Unit tests for the light RAG layer (chunking + cosine retrieval, fake embedder)."""

from __future__ import annotations

import re

import pytest

from src.rag import (
    RagIndex,
    build_context,
    chunk_text,
    retrieve_facets,
)


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder (no model needed).

    Each token bumps one fixed dimension, so cosine similarity tracks shared
    vocabulary — enough to assert retrieval ordering in tests.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                v[hash(tok) % self.dim] += 1.0
            out.append(v)
        return out


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def test_chunk_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_small_text_is_one_chunk():
    assert chunk_text("Just one short paragraph.") == ["Just one short paragraph."]


def test_chunk_packs_paragraphs_to_max_chars():
    text = "aaaa\n\nbbbb\n\ncccc"  # three 4-char blocks
    chunks = chunk_text(text, max_chars=10, overlap=2)
    # "aaaa\nbbbb" = 9 chars fits; adding "\ncccc" would exceed 10 -> new chunk.
    assert chunks == ["aaaa\nbbbb", "cccc"]


def test_chunk_windows_oversized_block_with_overlap():
    block = "x" * 25
    chunks = chunk_text(block, max_chars=10, overlap=3)
    # step = 10 - 3 = 7 -> windows start at 0,7,14,21
    assert len(chunks) == 4
    assert all(len(c) <= 10 for c in chunks)


# --------------------------------------------------------------------------- #
# Index + retrieval
# --------------------------------------------------------------------------- #
def test_index_retrieves_most_relevant_chunk_first():
    idx = RagIndex(FakeEmbedder())
    idx.add([
        "the method uses a convolutional neural network",
        "the results show improved accuracy on the benchmark",
        "the problem is detecting tumors in scans",
    ])
    assert len(idx) == 3
    top = idx.query("what are the results and accuracy?", k=1)
    assert "results" in top[0][0]


def test_query_empty_index():
    assert RagIndex(FakeEmbedder()).query("anything") == []


def test_retrieve_facets_dedupes_chunks():
    idx = RagIndex(FakeEmbedder())
    # One chunk that mentions everything would be top for several facets; it must
    # still appear only once in the merged context.
    idx.add([
        "this work addresses the problem method results and significance all at once",
        "an unrelated paragraph about gardening tomatoes",
    ])
    ctx = retrieve_facets(idx, k=1, max_chars=10_000)
    assert ctx.count("this work addresses the problem") == 1


def test_retrieve_facets_caps_length():
    idx = RagIndex(FakeEmbedder())
    idx.add(["problem " * 100, "method " * 100, "results " * 100])
    ctx = retrieve_facets(idx, k=2, max_chars=120)
    assert len(ctx) <= 120


# --------------------------------------------------------------------------- #
# build_context A/B switch
# --------------------------------------------------------------------------- #
def test_build_context_full_truncates():
    text = "para one.\n\n" + ("y" * 500)
    out = build_context(text, mode="full", full_max_chars=50)
    assert len(out) == 50


def test_build_context_rag_is_smaller_than_full():
    embedder = FakeEmbedder()
    text = "\n\n".join(
        [
            "the problem is detecting tumors in medical scans early",
            "the method trains a convolutional neural network on labeled data",
            "the results show a large accuracy gain over the prior baseline",
            "a tangent about lab logistics and coffee that is not relevant",
            "the significance is earlier diagnosis for patients and clinicians",
        ]
    )
    rag = build_context(text, mode="rag", embedder=embedder, chunk_max_chars=80, k=1, rag_max_chars=10_000)
    full = build_context(text, mode="full")
    assert rag and full
    assert len(rag) <= len(full)


def test_build_context_rag_needs_embedder():
    with pytest.raises(ValueError):
        build_context("x", mode="rag", embedder=None)


def test_build_context_unknown_mode():
    with pytest.raises(ValueError):
        build_context("x", mode="bogus")
