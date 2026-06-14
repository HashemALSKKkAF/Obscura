"""
rag.py
Retrieval-Augmented Generation over crawled dark-web content.

The old flow truncated every scraped page to ~2k chars and stuffed them all into
a single prompt — so most of the crawled evidence never reached the model, and
what did was cut arbitrarily. RAG fixes both: full page text is **chunked,
embedded, and indexed**, then only the chunks most relevant to the query are
retrieved and handed to :func:`llm.generate_summary`.

Privacy: embeddings are computed **locally** (FastEmbed / ONNX, no server, no
network once the model is cached) — dark-web content never leaves the machine.

Design (dependency-injected, like the rest of OBSCURA)
------------------------------------------------------
* ``Embedder``     — turns text into vectors. ``FastEmbedEmbedder`` is the local
  default; tests inject a deterministic fake.
* ``VectorStore``  — stores + similarity-searches vectors. ``InMemoryVectorStore``
  (pure NumPy cosine) is the zero-dependency default used in tests;
  ``ChromaVectorStore`` is the persistent production backend.
* ``RagIndex``     — ties an embedder to a store: ``add_content`` → ``retrieve``
  → ``build_context``.

Both heavy backends (FastEmbed, Chroma) are **lazily imported** so importing this
module — and running the test suite — never requires them.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np

_logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1000      # characters per chunk
DEFAULT_CHUNK_OVERLAP = 150    # characters shared between adjacent chunks
DEFAULT_TOP_K = 8
DEFAULT_CONTEXT_CHARS = 12_000
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


# ─────────────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    """A slice of a source document, with provenance for citation."""
    text: str
    source: str          # origin URL
    ordinal: int         # 0-based index of this chunk within its source


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split *text* into overlapping windows.

    Overlap preserves context that would otherwise be severed at a chunk
    boundary (a sentence split across two chunks still appears whole in one).
    Splitting is done on whitespace-normalised text at character boundaries —
    cheap, deterministic, and good enough for retrieval granularity.
    """
    text = " ".join((text or "").split())
    if not text:
        return []
    if chunk_size <= 0:
        return [text]
    step = max(1, chunk_size - max(0, overlap))
    return [text[i: i + chunk_size] for i in range(0, len(text), step) if text[i: i + chunk_size].strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Embedder interface + backends
# ─────────────────────────────────────────────────────────────────────────────

class Embedder(Protocol):
    """Turns text into fixed-dimension vectors."""
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local embeddings via FastEmbed (ONNX). No external service; the model is
    downloaded once and cached. Imported lazily so the dep is only needed when
    embeddings are actually computed."""

    def __init__(self, model_name: str = DEFAULT_EMBED_MODEL):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise RuntimeError(
                "FastEmbed is not installed. `pip install fastembed` or use a "
                "different embedder."
            ) from exc
        self._model = TextEmbedding(model_name=model_name)
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([text]))).tolist()


class HashingEmbedder:
    """Deterministic, dependency-free bag-of-words hashing embedder.

    Not for production quality, but fully local and instant — used as a fallback
    when FastEmbed is unavailable and as the default in tests, where determinism
    matters more than semantic nuance. Cosine similarity here reflects shared
    vocabulary, which is enough to verify retrieval wiring.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    @staticmethod
    def _bucket(token: str, dim: int) -> int:
        # Stable across processes (unlike built-in hash()), so a persisted index
        # stays consistent with queries embedded after a restart.
        digest = hashlib.md5(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "little") % dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.split(r"\W+", (text or "").lower()):
            if tok:
                v[self._bucket(tok, self.dim)] += 1.0
        return v.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# ─────────────────────────────────────────────────────────────────────────────
# Vector store interface + backends
# ─────────────────────────────────────────────────────────────────────────────

class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...
    def query(self, embedding: list[float], k: int) -> list[tuple[Chunk, float]]: ...


def _cosine(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Row-wise cosine similarity between *matrix* rows and *vector*."""
    if matrix.size == 0:
        return np.array([])
    m_norm = np.linalg.norm(matrix, axis=1)
    v_norm = np.linalg.norm(vector)
    denom = m_norm * v_norm
    denom[denom == 0] = 1e-12
    return (matrix @ vector) / denom


class InMemoryVectorStore:
    """Pure-NumPy cosine-similarity store. Zero external deps; the default used
    in tests and a graceful fallback when Chroma isn't installed."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        new = np.asarray(embeddings, dtype=np.float32)
        self._matrix = new if self._matrix is None else np.vstack([self._matrix, new])
        self._chunks.extend(chunks)

    def query(self, embedding: list[float], k: int) -> list[tuple[Chunk, float]]:
        if self._matrix is None or not self._chunks:
            return []
        sims = _cosine(self._matrix, np.asarray(embedding, dtype=np.float32))
        top = np.argsort(sims)[::-1][:k]
        return [(self._chunks[i], float(sims[i])) for i in top]


class ChromaVectorStore:
    """Persistent production store backed by Chroma (lazily imported).

    Passes embeddings in explicitly, so Chroma never loads its own default
    embedding model. ``persist_dir=None`` uses an ephemeral in-memory client."""

    def __init__(self, collection: str = "obscura", persist_dir: str | None = None):
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("chromadb is not installed. `pip install chromadb`.") from exc
        client = (
            chromadb.PersistentClient(path=persist_dir) if persist_dir
            else chromadb.EphemeralClient()
        )
        self._col = client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )
        self._next_id = 0

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        ids, docs, metas = [], [], []
        for ch in chunks:
            ids.append(str(self._next_id))
            self._next_id += 1
            docs.append(ch.text)
            metas.append({"source": ch.source, "ordinal": ch.ordinal})
        self._col.add(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)

    def query(self, embedding: list[float], k: int) -> list[tuple[Chunk, float]]:
        res = self._col.query(query_embeddings=[embedding], n_results=k)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out = []
        for doc, meta, dist in zip(docs, metas, dists):
            chunk = Chunk(text=doc, source=(meta or {}).get("source", ""),
                          ordinal=(meta or {}).get("ordinal", 0))
            out.append((chunk, 1.0 - float(dist)))  # cosine distance → similarity
        return out


# ─────────────────────────────────────────────────────────────────────────────
# RAG index
# ─────────────────────────────────────────────────────────────────────────────

class RagIndex:
    """Embed + index crawled content, then retrieve query-relevant chunks."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.embedder = embedder or default_embedder()
        self.store = store or InMemoryVectorStore()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._size = 0

    def add_content(self, content_map: dict[str, str]) -> int:
        """Chunk, embed, and index a ``{url: text}`` map. Returns chunks added."""
        chunks: list[Chunk] = []
        for url, text in (content_map or {}).items():
            for ordinal, piece in enumerate(
                chunk_text(text, chunk_size=self.chunk_size, overlap=self.chunk_overlap)
            ):
                chunks.append(Chunk(text=piece, source=url, ordinal=ordinal))
        if not chunks:
            return 0
        embeddings = self.embedder.embed_documents([c.text for c in chunks])
        self.store.add(chunks, embeddings)
        self._size += len(chunks)
        return len(chunks)

    def retrieve(self, query: str, k: int = DEFAULT_TOP_K) -> list[tuple[Chunk, float]]:
        if self._size == 0:
            return []
        return self.store.query(self.embedder.embed_query(query), k)

    def build_context(
        self,
        query: str,
        k: int = DEFAULT_TOP_K,
        max_chars: int = DEFAULT_CONTEXT_CHARS,
    ) -> str:
        """Retrieve top-k chunks and format them as a source-attributed context
        block for the LLM, capped at *max_chars* total."""
        hits = self.retrieve(query, k)
        blocks, total = [], 0
        for chunk, score in hits:
            block = f"[Source: {chunk.source} | relevance={score:.2f}]\n{chunk.text}"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
        return "\n\n".join(blocks)


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def default_embedder() -> Embedder:
    """Local embedder, preferring FastEmbed; falls back to the hashing embedder
    if FastEmbed isn't installed so the feature degrades instead of crashing."""
    try:
        return FastEmbedEmbedder()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("FastEmbed unavailable (%s); using HashingEmbedder fallback.", exc)
        return HashingEmbedder()


def build_index(
    *,
    backend: str = "memory",
    embedder: Embedder | None = None,
    persist_dir: str | None = None,
    collection: str = "obscura",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> RagIndex:
    """Construct a :class:`RagIndex` with the chosen store backend.

    backend: ``"memory"`` (NumPy, default) or ``"chroma"`` (persistent).
    """
    if backend == "chroma":
        store: VectorStore = ChromaVectorStore(collection=collection, persist_dir=persist_dir)
    elif backend == "memory":
        store = InMemoryVectorStore()
    else:
        raise ValueError(f"unknown vector-store backend: {backend!r}")
    return RagIndex(embedder=embedder, store=store,
                    chunk_size=chunk_size, chunk_overlap=chunk_overlap)
