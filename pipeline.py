"""
pipeline.py
The investigation orchestration pipeline, decoupled from Flask.

The old app.py embedded the whole refine → search → filter → scrape →
summarize → persist flow inside a Flask streaming generator, which made it
impossible to test and tangled HTTP with business logic. :class:`InvestigationPipeline`
encapsulates that flow and yields progress events; the route just turns those
events into Server-Sent Events.

0.4.0 adds two opt-in stages, off by default so the classic flow is unchanged:
  * ``deep=True``    — replace the single-hop scrape with a relevance-guided
    deep crawl (:mod:`deep_search`) that follows links into onion services.
  * ``use_rag=True`` — embed the gathered content and retrieve only the chunks
    most relevant to the query (:mod:`rag`), instead of feeding raw/truncated
    text straight to the LLM.

Collaborators are injected (defaulting to the real implementations) so the
pipeline can be unit-tested end-to-end with fakes and no network.
"""
import logging

import deep_search
import investigations as inv_db
import rag
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
        deep_crawl=deep_search.deep_crawl,
        to_content_map=deep_search.to_content_map,
        index_factory=None,
    ):
        self.llm = llm
        self._refine = refine
        self._search = search
        self._filter = filter_fn
        self._scrape = scrape
        self._summarize = summarize
        self._repo = repo
        self._deep_crawl = deep_crawl
        self._to_content_map = to_content_map
        # Built lazily and only when use_rag=True (constructing the real index
        # loads the local embedding model). Injected as a fake in tests.
        self._index_factory = index_factory or (lambda: rag.build_index(backend="memory"))

    def run(
        self,
        query: str,
        model: str,
        preset: str = "threat_intel",
        threads: int = 4,
        max_results: int = 50,
        max_scrape: int = 10,
        max_content_chars: int = 2000,
        deep: bool = False,
        deep_max_depth: int = deep_search.DEFAULT_MAX_DEPTH,
        deep_max_pages: int = deep_search.DEFAULT_MAX_PAGES,
        use_rag: bool = False,
        rag_top_k: int = rag.DEFAULT_TOP_K,
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

        # ── Gather content: deep crawl (opt-in) or classic single-hop scrape ──
        deep_pages = 0
        if deep:
            yield {"status": f"Deep crawling from {len(filtered)} seeds (depth≤{deep_max_depth}, budget {deep_max_pages})..."}
            pages = self._deep_crawl(
                filtered, refined,
                max_depth=deep_max_depth, max_pages=deep_max_pages,
                max_workers=threads,
            )
            content = self._to_content_map(pages)
            deep_pages = len(content)
        else:
            yield {"status": f"Scraping {len(filtered)} selected sources..."}
            content = self._scrape(
                filtered, max_workers=threads, max_return_chars=max_content_chars,
            )

        # ── Build the LLM input: RAG retrieval (opt-in) or raw content ──
        if use_rag and content:
            yield {"status": f"Indexing {len(content)} sources & retrieving top {rag_top_k}..."}
            index = self._index_factory()
            index.add_content(content)
            summary_input = index.build_context(refined, k=rag_top_k)
        else:
            summary_input = content

        yield {"status": "Generating final intelligence report..."}
        summary = self._summarize(
            self.llm, query, summary_input,
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
            "scraped": content,
            "summary": summary,
            "deep": deep,
            "deep_pages": deep_pages,
            "rag": bool(use_rag and content),
        }
