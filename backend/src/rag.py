"""Light RAG: chunk article text, embed, retrieve only the relevant chunks.

The paper-summary experiment uses this to feed the LLM just the parts of an
article that matter (saving context tokens), and to A/B that against the full
text so we can confirm retrieval isn't dropping anything. Kept deliberately tiny
and dependency-light:

* **chunking** is pure Python (paragraph packing + windowing of oversized blocks);
* **retrieval** is cosine similarity over an in-memory list of vectors (pure
  Python, no numpy needed at query time);
* the only heavy piece is the **embedding model**. It sits behind the
  :class:`Embedder` Protocol so unit tests inject a fake; the real
  :class:`MiniLMEmbedder` lazily imports sentence-transformers (the
  ``backend[rag]`` extra) and is only touched by the live harness.

``build_context(text, mode=...)`` is the single A/B switch the harness flips
between ``"rag"`` and ``"full"``.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

# Default facet queries: a paper summary needs the problem, the method, the
# results, and the significance, so we retrieve chunks for each and merge them.
DEFAULT_FACETS = (
    "What problem or question does this work address?",
    "What method, system, or approach does it use?",
    "What are the main results, findings, or contributions?",
    "Why does this work matter and who benefits from it?",
)


class Embedder(Protocol):
    """Maps a list of texts to a list of equal-length vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# --------------------------------------------------------------------------- #
# Chunking (pure)
# --------------------------------------------------------------------------- #
def _split_blocks(text: str) -> list[str]:
    """Split into paragraph blocks on blank lines."""

    return [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]


def _window(s: str, max_chars: int, overlap: int) -> list[str]:
    """Slice an oversized block into overlapping windows of ``max_chars``."""

    step = max(1, max_chars - overlap)
    out = [s[i : i + max_chars].strip() for i in range(0, len(s), step)]
    return [c for c in out if c]


def chunk_text(text: str, *, max_chars: int = 900, overlap: int = 150) -> list[str]:
    """Chunk ``text`` for embedding.

    Paragraphs are greedily packed up to ``max_chars`` on natural boundaries; a
    single paragraph longer than ``max_chars`` is windowed with ``overlap`` so a
    fact split across the cut still lands whole in one window.
    """

    if not text or not text.strip():
        return []
    chunks: list[str] = []
    cur = ""
    for b in _split_blocks(text):
        if len(b) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_window(b, max_chars, overlap))
            continue
        if cur and len(cur) + 1 + len(b) > max_chars:
            chunks.append(cur)
            cur = b
        else:
            cur = f"{cur}\n{b}" if cur else b
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- #
# Embedding
# --------------------------------------------------------------------------- #
class MiniLMEmbedder:
    """Local sentence-transformers embedder (all-MiniLM-L6-v2 by default).

    Lazily imported so the core agent never pays for torch. Install with
    ``pip install -e 'backend[rag]'`` before the live harness uses it.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only off the [rag] extra
            raise RuntimeError(
                "sentence-transformers is not installed; run "
                "`pip install -e 'backend[rag]'` to use MiniLMEmbedder"
            ) from exc
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in v] for v in vecs]


# --------------------------------------------------------------------------- #
# Index + retrieval (pure cosine)
# --------------------------------------------------------------------------- #
def _normalize(v: list[float]) -> list[float]:
    mag = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / mag for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class RagIndex:
    """In-memory vector index over text chunks; cosine-ranked retrieval."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._chunks: list[str] = []
        self._vecs: list[list[float]] = []

    @classmethod
    def from_text(
        cls, text: str, embedder: Embedder, *, max_chars: int = 900, overlap: int = 150
    ) -> "RagIndex":
        idx = cls(embedder)
        idx.add(chunk_text(text, max_chars=max_chars, overlap=overlap))
        return idx

    def add(self, chunks: list[str]) -> None:
        chunks = [c for c in chunks if c and c.strip()]
        if not chunks:
            return
        for chunk, vec in zip(chunks, self._embedder.embed(chunks)):
            self._chunks.append(chunk)
            self._vecs.append(_normalize(vec))

    def query(self, text: str, k: int = 4) -> list[tuple[str, float]]:
        """Return the ``k`` most similar chunks to ``text`` as (chunk, score)."""

        if not self._chunks:
            return []
        qv = _normalize(self._embedder.embed([text])[0])
        scored = sorted(
            ((_dot(qv, v), i) for i, v in enumerate(self._vecs)),
            key=lambda t: t[0],
            reverse=True,
        )
        return [(self._chunks[i], score) for score, i in scored[:k]]

    def __len__(self) -> int:
        return len(self._chunks)


def retrieve_facets(
    index: RagIndex,
    *,
    facets: tuple[str, ...] = DEFAULT_FACETS,
    k: int = 2,
    max_chars: int = 2400,
) -> str:
    """Retrieve top-``k`` chunks per facet, dedupe, and join into one context.

    Facet order is preserved (problem first, significance last); a chunk that is
    top-ranked for several facets appears once. The result is capped at
    ``max_chars`` so 'rag' mode stays meaningfully smaller than full text.
    """

    seen: set[str] = set()
    picked: list[str] = []
    for facet in facets:
        for chunk, _score in index.query(facet, k=k):
            key = chunk[:80]
            if key in seen:
                continue
            seen.add(key)
            picked.append(chunk)
    context = "\n\n".join(picked)
    if max_chars and len(context) > max_chars:
        context = context[:max_chars].rstrip()
    return context


def build_context(
    text: str,
    *,
    mode: str,
    embedder: Embedder | None = None,
    full_max_chars: int = 6000,
    chunk_max_chars: int = 900,
    overlap: int = 150,
    facets: tuple[str, ...] = DEFAULT_FACETS,
    k: int = 2,
    rag_max_chars: int = 2400,
) -> str:
    """Assemble the grounding context for one summary, by ``mode``.

    ``"full"`` returns the whole source (truncated to ``full_max_chars``);
    ``"rag"`` chunks + embeds + retrieves the facet-relevant chunks. The two are
    directly comparable: same source, different amount fed to the model.
    """

    text = (text or "").strip()
    if not text:
        return ""
    if mode == "full":
        return text[:full_max_chars]
    if mode == "rag":
        if embedder is None:
            raise ValueError("rag mode requires an embedder")
        index = RagIndex.from_text(text, embedder, max_chars=chunk_max_chars, overlap=overlap)
        return retrieve_facets(index, facets=facets, k=k, max_chars=rag_max_chars)
    raise ValueError(f"unknown context mode: {mode!r}")
