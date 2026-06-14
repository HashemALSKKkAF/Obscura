"""Unit tests for rag.py — chunking, embedders, vector stores, and the
RagIndex retrieval flow. Uses the deterministic HashingEmbedder + in-memory
store so nothing downloads a model or hits the network."""
import numpy as np
import pytest

import rag
from rag import Chunk, HashingEmbedder, InMemoryVectorStore, RagIndex, chunk_text


# ── chunking ──────────────────────────────────────────────────────────────────

def test_chunk_text_overlap_and_coverage():
    text = "word " * 600  # 3000 chars after normalisation-ish
    chunks = chunk_text(text, chunk_size=1000, overlap=200)
    assert len(chunks) >= 3
    assert all(len(c) <= 1000 for c in chunks)
    # overlap: end of chunk 0 should reappear at the start region of chunk 1
    assert chunks[0][-50:] in (chunks[0] + chunks[1])


def test_chunk_text_empty_and_normalises_whitespace():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []
    assert chunk_text("a\n\n   b\tc") == ["a b c"]


# ── hashing embedder ─────────────────────────────────────────────────────────

def test_hashing_embedder_is_stable_and_fixed_dim():
    e = HashingEmbedder(dim=64)
    v1 = e.embed_query("ransomware leak")
    v2 = e.embed_query("ransomware leak")
    assert v1 == v2 and len(v1) == 64          # deterministic, fixed dimension
    assert e.embed_query("ransomware leak") != e.embed_query("cat pictures")


# ── in-memory store ──────────────────────────────────────────────────────────

def test_cosine_helper_matches_numpy():
    m = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    sims = rag._cosine(m, np.array([1.0, 0.0], dtype=np.float32))
    assert sims[0] == pytest.approx(1.0)
    assert sims[1] == pytest.approx(0.0)


def test_in_memory_store_returns_most_similar_first():
    store = InMemoryVectorStore()
    chunks = [Chunk("a", "u1", 0), Chunk("b", "u2", 0)]
    store.add(chunks, [[1.0, 0.0], [0.0, 1.0]])
    hits = store.query([0.9, 0.1], k=2)
    assert hits[0][0].text == "a"           # closest to [1,0]
    assert hits[0][1] > hits[1][1]          # scores sorted descending


def test_empty_store_query_returns_empty():
    assert InMemoryVectorStore().query([1.0, 0.0], k=3) == []


# ── RagIndex end-to-end ──────────────────────────────────────────────────────

def _index():
    return RagIndex(embedder=HashingEmbedder(dim=256), store=InMemoryVectorStore())


def test_rag_index_add_and_retrieve_relevant_source():
    idx = _index()
    added = idx.add_content({
        "http://a.onion": "ransomware gang leaks corporate databases for extortion",
        "http://b.onion": "vintage stamp collecting and philately hobby community",
    })
    assert added >= 2
    hits = idx.retrieve("ransomware database leak", k=1)
    assert hits and hits[0][0].source == "http://a.onion"


def test_rag_index_empty_retrieve_is_safe():
    assert _index().retrieve("anything") == []


def test_build_context_attributes_sources_and_caps_length():
    idx = _index()
    idx.add_content({"http://a.onion": "credential dumps and stolen logins " * 50})
    ctx = idx.build_context("stolen credentials", k=5, max_chars=400)
    assert "[Source: http://a.onion" in ctx
    assert len(ctx) <= 400 + 200  # cap respected (allow one block's header slack)


# ── factory ──────────────────────────────────────────────────────────────────

def test_build_index_rejects_unknown_backend():
    with pytest.raises(ValueError):
        rag.build_index(backend="nope", embedder=HashingEmbedder())


def test_build_index_memory_backend_uses_in_memory_store():
    idx = rag.build_index(backend="memory", embedder=HashingEmbedder())
    assert isinstance(idx.store, InMemoryVectorStore)
