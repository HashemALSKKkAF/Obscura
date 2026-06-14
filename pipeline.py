"""
pipeline.py
The investigation orchestration pipeline, decoupled from Flask.

The old app.py embedded the whole refine → search → filter → scrape →
summarize → persist flow inside a Flask streaming generator, which made it
impossible to test and tangled HTTP with business logic. :class:`InvestigationPipeline`
encapsulates that flow and yields progress events; the route just turns those
events into Server-Sent Events.

Collaborators are injected (defaulting to the real implementations) so the
pipeline can be unit-tested end-to-end with fakes and no network.
"""
import logging

import investigations as inv_db
from llm import filter_results, generate_summary, refine_query
from scrape import scrape_multiple
from search import get_search_results

_logger = logging.getLogger(__name__)


class InvestigationPipeline:
    """Runs an investigation and yields progress events.

    Usage::

        pipeline = InvestigationPipeline(llm)
        for event in pipeline.run(query="...", model="gpt-4.1"):
            ...  # event is a dict; the final one has {"done": True, ...}
    """

    def __init__(
        self,
        llm,
        *,
        refine=refine_query,
        search=get_search_results,
        filter_fn=filter_results,
        scrape=scrape_multiple,
        summarize=generate_summary,
        repo=inv_db,
    ):
        self.llm = llm
        self._refine = refine
        self._search = search
        self._filter = filter_fn
        self._scrape = scrape
        self._summarize = summarize
        self._repo = repo

    def run(
        self,
        query: str,
        model: str,
        preset: str = "threat_intel",
        threads: int = 4,
        max_results: int = 50,
        max_scrape: int = 10,
        max_content_chars: int = 2000,
    ):
        """Yield progress dicts, then a final dict with the saved id + artifacts."""
        yield {"status": "Refining query..."}
        refined = self._refine(self.llm, query)

        yield {"status": "Searching dark web for: " + refined}
        results = self._search(refined, max_workers=threads)
        if len(results) > max_results:
            results = results[:max_results]

        yield {"status": f"Filtering {len(results)} results..."}
        filtered = self._filter(self.llm, refined, results)
        if len(filtered) > max_scrape:
            filtered = filtered[:max_scrape]

        yield {"status": f"Scraping {len(filtered)} selected sources..."}
        scraped = self._scrape(filtered, max_workers=threads, max_return_chars=max_content_chars)

        yield {"status": "Generating final intelligence report..."}
        summary = self._summarize(
            self.llm, query, scraped,
            preset=preset, custom_instructions="", system_prompt_override=None,
        )

        inv_id = self._repo.save_investigation(
            query=query,
            refined_query=refined,
            model=model,
            preset_label=preset,
            sources=filtered,
            summary=summary,
            status="complete",
        )

        yield {
            "done": True,
            "inv_id": inv_id,
            "refined": refined,
            "results": results,
            "filtered": filtered,
            "scraped": scraped,
            "summary": summary,
        }
