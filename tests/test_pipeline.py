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
