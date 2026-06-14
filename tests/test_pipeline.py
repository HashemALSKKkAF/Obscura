"""Tests for the investigation pipeline orchestration (fakes, no network)."""
from pipeline import InvestigationPipeline


class _FakeRepo:
    def __init__(self):
        self.saved = None

    def save_investigation(self, **kwargs):
        self.saved = kwargs
        return 123


def test_pipeline_orders_stages_applies_caps_and_persists():
    repo = _FakeRepo()
    pipe = InvestigationPipeline(
        llm="FAKE_LLM",
        refine=lambda llm, q: f"refined:{q}",
        search=lambda refined, max_workers=5: [
            {"link": f"http://r{i}.onion", "title": f"t{i}"} for i in range(60)
        ],
        filter_fn=lambda llm, refined, results: results[:30],
        scrape=lambda filtered, max_workers=5, max_return_chars=2000: {
            f["link"]: "content" for f in filtered
        },
        summarize=lambda llm, q, scraped, **kw: "SUMMARY",
        repo=repo,
    )

    events = list(pipe.run(query="hello", model="gpt-4.1", max_results=50, max_scrape=10))

    statuses = [e for e in events if "status" in e]
    final = events[-1]

    assert len(statuses) == 5                 # refine, search, filter, scrape, summarize
    assert final["done"] is True
    assert final["inv_id"] == 123
    assert len(final["results"]) == 50        # max_results cap applied
    assert len(final["filtered"]) == 10       # max_scrape cap applied
    assert len(final["scraped"]) == 10
    assert repo.saved["query"] == "hello"
    assert repo.saved["summary"] == "SUMMARY"
    assert repo.saved["status"] == "complete"
    assert repo.saved["refined_query"] == "refined:hello"


def test_pipeline_passes_preset_through_to_summarize():
    captured = {}

    def fake_summarize(llm, q, scraped, **kw):
        captured.update(kw)
        return "S"

    pipe = InvestigationPipeline(
        llm="L",
        refine=lambda llm, q: q,
        search=lambda refined, max_workers=5: [],
        filter_fn=lambda llm, refined, results: [],
        scrape=lambda filtered, max_workers=5, max_return_chars=2000: {},
        summarize=fake_summarize,
        repo=_FakeRepo(),
    )
    list(pipe.run(query="q", model="m", preset="ransomware_malware"))
    assert captured["preset"] == "ransomware_malware"


# ── 0.4.0 opt-in paths ───────────────────────────────────────────────────────

def _base_pipe(**overrides):
    kwargs = dict(
        llm="L",
        refine=lambda llm, q: f"refined:{q}",
        search=lambda refined, max_workers=5: [{"link": "http://a.onion", "title": "t"}],
        filter_fn=lambda llm, refined, results: results,
        scrape=lambda filtered, max_workers=5, max_return_chars=2000: {"http://a.onion": "SHALLOW"},
        summarize=lambda llm, q, content, **kw: "SUMMARY",
        repo=_FakeRepo(),
    )
    kwargs.update(overrides)
    return InvestigationPipeline(**kwargs)


def test_deep_path_replaces_scrape_with_deep_crawl():
    calls = {"deep": 0, "scrape": 0}

    def fake_deep_crawl(seeds, query, *, max_depth, max_pages, max_workers):
        calls["deep"] += 1
        return ["page-objs"]  # opaque; mapped below

    pipe = _base_pipe(
        deep_crawl=fake_deep_crawl,
        to_content_map=lambda pages: {"http://a.onion": "DEEP", "http://b.onion": "DEEP2"},
        scrape=lambda *a, **k: calls.__setitem__("scrape", calls["scrape"] + 1) or {},
    )
    final = list(pipe.run(query="q", model="m", deep=True))[-1]
    assert calls["deep"] == 1 and calls["scrape"] == 0   # deep crawl used, scrape skipped
    assert final["deep"] is True and final["deep_pages"] == 2
    assert final["scraped"] == {"http://a.onion": "DEEP", "http://b.onion": "DEEP2"}


def test_rag_path_feeds_retrieved_context_to_summarize():
    captured = {}

    class _FakeIndex:
        def add_content(self, content):
            captured["indexed"] = content
        def build_context(self, query, k):
            captured["k"] = k
            return "RETRIEVED-CONTEXT"

    pipe = _base_pipe(
        summarize=lambda llm, q, content, **kw: captured.setdefault("content", content) or "S",
        index_factory=lambda: _FakeIndex(),
    )
    final = list(pipe.run(query="q", model="m", use_rag=True, rag_top_k=5))[-1]
    assert captured["indexed"] == {"http://a.onion": "SHALLOW"}  # scraped content indexed
    assert captured["content"] == "RETRIEVED-CONTEXT"            # retrieval fed to LLM
    assert captured["k"] == 5
    assert final["rag"] is True


def test_default_path_unchanged_no_deep_no_rag():
    captured = {}
    pipe = _base_pipe(
        summarize=lambda llm, q, content, **kw: captured.setdefault("content", content) or "S",
    )
    final = list(pipe.run(query="q", model="m"))[-1]
    assert captured["content"] == {"http://a.onion": "SHALLOW"}  # raw scrape, no retrieval
    assert final["deep"] is False and final["rag"] is False
