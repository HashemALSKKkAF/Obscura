"""Unit tests for summarizer.py — content normalisation, batching, and the
map-reduce orchestration. The LLM is injected as a fake; no model/network."""
import summarizer
from summarizer import MAP_SYSTEM_PROMPT, batch_documents, generate_summary


class _FakeLLM:
    """Records every (system_prompt, query, content) call. Returns 'M' for map
    calls (so combined notes stay tiny) and 'FINAL-REPORT' for the reduce."""
    def __init__(self):
        self.calls = []

    def __call__(self, system_prompt, query, content):
        self.calls.append({"system": system_prompt, "query": query, "content": content})
        return "M" if system_prompt == MAP_SYSTEM_PROMPT else "FINAL-REPORT"

    @property
    def map_calls(self):
        return [c for c in self.calls if c["system"] == MAP_SYSTEM_PROMPT]

    @property
    def reduce_calls(self):
        return [c for c in self.calls if c["system"] != MAP_SYSTEM_PROMPT]


# ── normalisation ─────────────────────────────────────────────────────────────

def test_normalize_dict_str_and_other():
    assert summarizer._normalize_content({"u": "t", "e": ""}) == [("u", "t")]
    assert summarizer._normalize_content("ctx") == [("", "ctx")]
    assert summarizer._normalize_content("") == []
    assert summarizer._normalize_content(123) == [("", "123")]


# ── batching ─────────────────────────────────────────────────────────────────

def test_batch_documents_packs_within_budget():
    docs = [("a", "x" * 80), ("b", "y" * 80)]
    batches = batch_documents(docs, batch_chars=100)
    assert len(batches) == 2  # 80 + 80 can't share a 100-char batch


def test_batch_documents_splits_oversized_single_doc():
    docs = [("a", "z" * 250)]
    batches = batch_documents(docs, batch_chars=100)
    assert len(batches) == 3  # 100 + 100 + 50 — nothing dropped
    assert sum(b.count("z") for b in batches) == 250


# ── single-batch path (no extra cost) ────────────────────────────────────────

def test_single_batch_makes_one_reduce_call_only():
    llm = _FakeLLM()
    out = generate_summary(
        "L", "q", {"http://a.onion": "small content"},
        preset="threat_intel", llm_call=llm, batch_chars=10_000,
    )
    assert out == "FINAL-REPORT"
    assert len(llm.map_calls) == 0 and len(llm.reduce_calls) == 1
    # final call carries the formatted source
    assert "http://a.onion" in llm.reduce_calls[0]["content"]


# ── map-reduce path ──────────────────────────────────────────────────────────

def test_map_reduce_processes_every_batch_then_reduces():
    llm = _FakeLLM()
    content = {"http://a.onion": "x" * 80, "http://b.onion": "y" * 80}
    out = generate_summary("L", "q", content, llm_call=llm, batch_chars=100)
    assert out == "FINAL-REPORT"
    assert len(llm.map_calls) == 2          # one map call per batch — all seen
    assert len(llm.reduce_calls) == 1       # one synthesis call
    # the reduce sees the consolidated notes, not the raw content
    assert "Notes (batch 1)" in llm.reduce_calls[0]["content"]


# ── prompt resolution parity with llm.generate_summary ───────────────────────

def test_system_prompt_override_and_custom_instructions():
    sp = summarizer._resolve_system_prompt("threat_intel", "phishing kits", "OVERRIDE")
    assert sp.startswith("OVERRIDE")
    assert "Additionally focus on: phishing kits" in sp
