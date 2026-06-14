"""
deep_search.py
Relevance-guided deep crawling of the dark web.

Where :mod:`search` does a single hop (search engine → result links), this
module follows links *out of* crawled pages to dive deeper into onion services.

It uses **best-first search** over a priority frontier: every discovered link is
scored by how well its anchor text + URL match the query, and only the most
promising links are expanded — bounded by a maximum depth and a global page
budget. That keeps the crawl focused and finite instead of exploding
combinatorially (a fixed-depth crawl of branching factor *b* to depth *d* visits
*b^d* pages; a scored frontier with a hard budget visits at most ``max_pages``).

Design notes
------------
* The traversal is pure and testable: the network call is injected as ``fetch``.
  The default fetcher (:func:`fetch_page`) uses the shared Tor session, but unit
  tests pass a fake that returns a canned link graph — no Tor required.
* De-duplication reuses :func:`search._dedup_key` so a URL discovered by the
  deep crawl collapses with the same URL found by the flat search.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import tor_session
from constants import USER_AGENTS
from search import _dedup_key

_logger = logging.getLogger(__name__)

# Matches v2 (16-char) and v3 (56-char) onion hosts plus an optional path.
ONION_URL_RE = re.compile(r"https?://[a-z2-7]{16,56}\.onion[^\s\"'<>]*", re.IGNORECASE)

# Tunable defaults — overridable per call and (later) from the UI / config.
DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_PAGES = 25
DEFAULT_PER_PAGE_LINKS = 10
DEFAULT_MIN_LINK_SCORE = 1
DEFAULT_MAX_WORKERS = 5
MAX_EXTRACTED_TEXT_CHARS = 50_000
MAX_DOWNLOAD_BYTES = 1_000_000


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PageResult:
    """One fetched page and the links discovered on it."""
    url: str
    title: str = ""
    text: str = ""
    # Discovered outbound links as (absolute_url, anchor_text) pairs.
    links: list[tuple[str, str]] = field(default_factory=list)
    success: bool = False
    depth: int = 0
    score: float = 0.0
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def query_terms(query: str) -> list[str]:
    """Lower-cased query tokens longer than two characters."""
    return [t.lower() for t in re.split(r"\W+", query or "") if len(t) > 2]


def relevance_score(text: str, terms: list[str]) -> float:
    """Score text by how many distinct query terms it contains.

    Distinct-term coverage (not raw frequency) is deliberate: it rewards a page
    that touches many facets of the query over one that spams a single term.
    """
    if not terms:
        return 0.0
    haystack = (text or "").lower()
    return float(sum(1 for term in set(terms) if term in haystack))


def _link_score(url: str, anchor: str, terms: list[str]) -> float:
    """Priority of a candidate link. Anchor text is weighted above the URL,
    since onion hosts are opaque hashes and rarely carry meaning."""
    return relevance_score(anchor, terms) * 2.0 + relevance_score(url, terms)


# ─────────────────────────────────────────────────────────────────────────────
# Link extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_links(html: str, base_url: str = "") -> list[tuple[str, str]]:
    """Return ``(absolute_onion_url, anchor_text)`` pairs found in *html*.

    Relative hrefs are resolved against *base_url*; only .onion targets are
    kept. Duplicate URLs within the page collapse to their first anchor.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        absolute = urljoin(base_url, href) if base_url else href
        match = ONION_URL_RE.search(absolute)
        if not match:
            continue
        url = match.group(0)
        key = _dedup_key(url)
        if key in seen:
            continue
        seen.add(key)
        out.append((url, a.get_text(strip=True)))
    return out


def _html_to_text(html: str, title_hint: str = "") -> tuple[str, str]:
    """Extract (title, clean_text) from HTML, capped at MAX_EXTRACTED_TEXT_CHARS."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.extract()
    title = (soup.title.get_text(strip=True) if soup.title else "") or title_hint
    text = " ".join(soup.get_text(separator=" ").split())[:MAX_EXTRACTED_TEXT_CHARS]
    return title, text


# ─────────────────────────────────────────────────────────────────────────────
# Default network fetcher (injectable)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_page(url: str, title_hint: str = "") -> PageResult:
    """Fetch one page over the shared Tor session and parse text + links.

    This is the production ``fetch`` used by :func:`deep_crawl`. Network errors
    are swallowed into ``PageResult(success=False, error=...)`` so a single dead
    onion never aborts the crawl.
    """
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    response = None
    try:
        # retries=0: deep crawl visits many pages under a budget; a slow/dead
        # onion should fail fast so the wave moves on, not retry 3× at timeout.
        session = tor_session.get_tor_session(retries=0)
        response = session.get(url, headers=headers, timeout=(10, 30), stream=True)
        if response.status_code != 200:
            return PageResult(url=url, title=title_hint, error=f"HTTP {response.status_code}")

        chunks, read = [], 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            read += len(chunk)
            if read > MAX_DOWNLOAD_BYTES:
                break
            chunks.append(chunk)
        html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")

        title, text = _html_to_text(html, title_hint)
        links = extract_links(html, base_url=url)
        return PageResult(url=url, title=title, text=text, links=links, success=True)
    except Exception as exc:  # noqa: BLE001 — one bad onion must not kill the crawl
        _logger.debug("[DeepSearch] fetch failed for %s: %s", url, exc)
        return PageResult(url=url, title=title_hint, error=str(exc))
    finally:
        if response is not None:
            response.close()


# ─────────────────────────────────────────────────────────────────────────────
# Priority frontier
# ─────────────────────────────────────────────────────────────────────────────

class _Frontier:
    """Max-priority queue of pending URLs, de-duplicated by normalized key.

    ``heapq`` is a min-heap, so scores are negated. A monotonic counter breaks
    ties deterministically (FIFO among equal scores) and stops the heap from
    ever comparing the unorderable payload tuples.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, str, str, int]] = []
        self._counter = itertools.count()
        self._enqueued: set[str] = set()

    def push(self, url: str, anchor: str, depth: int, score: float) -> bool:
        key = _dedup_key(url)
        if not key or key in self._enqueued:
            return False
        self._enqueued.add(key)
        heapq.heappush(self._heap, (-score, next(self._counter), url, anchor, depth))
        return True

    def pop(self) -> tuple[str, str, int, float]:
        neg_score, _, url, anchor, depth = heapq.heappop(self._heap)
        return url, anchor, depth, -neg_score

    def __len__(self) -> int:
        return len(self._heap)


# ─────────────────────────────────────────────────────────────────────────────
# Best-first deep crawl
# ─────────────────────────────────────────────────────────────────────────────

def deep_crawl(
    seeds: list,
    query: str,
    *,
    fetch=fetch_page,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_pages: int = DEFAULT_MAX_PAGES,
    per_page_links: int = DEFAULT_PER_PAGE_LINKS,
    min_link_score: float = DEFAULT_MIN_LINK_SCORE,
    max_workers: int = DEFAULT_MAX_WORKERS,
    progress_callback=None,
) -> list[PageResult]:
    """Best-first deep crawl starting from *seeds*, guided by *query*.

    Crawls in **waves**: each iteration pops the current best ``max_workers``
    candidates off the frontier and fetches them concurrently, then expands
    their children back onto the frontier. Onion fetches are network-bound
    (10–45s each), so this turns wall-clock ``O(pages × latency)`` into roughly
    ``O(pages / max_workers × latency)`` while keeping the relevance-guided
    order: a wave always takes the highest-scoring pending links.

    Args:
        seeds:           Seed results as dicts ({"link"/"url", "title"}) or URL strings.
        query:           Drives link prioritisation.
        fetch:           ``fetch(url, title_hint) -> PageResult`` (injected for tests).
        max_depth:       How many link-hops past the seeds to follow (seeds = depth 0).
        max_pages:       Hard cap on pages fetched — the crawl's global budget.
        per_page_links:  Max child links enqueued from any single page.
        min_link_score:  Drop child links scoring below this (0 keeps everything).
        max_workers:     Concurrent fetches per wave.
        progress_callback: Optional ``callable(fetched_count, max_pages)``.

    Returns:
        Successfully-fetched :class:`PageResult` objects, highest score first.
    """
    terms = query_terms(query)
    frontier = _Frontier()
    visited: set[str] = set()
    workers = max(1, int(max_workers))

    for seed in seeds:
        url, title = _seed_fields(seed)
        if url:
            # Seeds start at the top of the frontier (they already passed the
            # flat search + LLM filter); a tiny title bonus orders among them.
            frontier.push(url, title, 0, score=1e6 + relevance_score(title, terms))

    results: list[PageResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while frontier and len(results) < max_pages:
            # Pop a wave of unvisited candidates (single-threaded; the frontier
            # and visited set are only mutated here, so no locking is needed).
            wave: list[tuple[str, str, int]] = []
            while frontier and len(wave) < workers and (len(results) + len(wave)) < max_pages:
                url, anchor, depth, _score = frontier.pop()
                key = _dedup_key(url)
                if key in visited:
                    continue
                visited.add(key)
                wave.append((url, anchor, depth))
            if not wave:
                continue

            futures = {pool.submit(fetch, u, a): (u, a, d) for (u, a, d) in wave}
            fetched: list[PageResult] = []
            for future in as_completed(futures):
                _u, _a, depth = futures[future]
                try:
                    page = future.result()
                except Exception as exc:  # noqa: BLE001 — one bad fetch can't kill the wave
                    _logger.debug("[DeepSearch] worker error: %s", exc)
                    continue
                page.depth = depth
                page.score = relevance_score(f"{page.title} {page.text}", terms)
                fetched.append(page)

            # Process highest-scoring pages first so expansion order is
            # deterministic regardless of which fetch finished first.
            fetched.sort(key=lambda p: p.score, reverse=True)
            for page in fetched:
                if not page.success or len(results) >= max_pages:
                    continue
                results.append(page)
                if progress_callback:
                    try:
                        progress_callback(len(results), max_pages)
                    except Exception:  # noqa: BLE001 — progress is best-effort
                        pass
                if page.depth < max_depth:
                    _expand(frontier, page, terms, visited, per_page_links, min_link_score)

    results.sort(key=lambda p: p.score, reverse=True)
    _logger.info(
        "[DeepSearch] crawled %d pages (depth≤%d, budget=%d, workers=%d) for query=%r",
        len(results), max_depth, max_pages, workers, query,
    )
    return results


def _expand(frontier, page, terms, visited, per_page_links, min_link_score) -> None:
    """Score *page*'s outbound links and push the best onto *frontier*."""
    scored_children = sorted(
        (
            (_link_score(child_url, child_anchor, terms), child_url, child_anchor)
            for child_url, child_anchor in page.links
            if _dedup_key(child_url) not in visited
        ),
        key=lambda t: t[0],
        reverse=True,
    )
    enqueued = 0
    for child_score, child_url, child_anchor in scored_children:
        if enqueued >= per_page_links:
            break
        if child_score < min_link_score:
            break  # sorted desc — nothing below clears the bar either
        if frontier.push(child_url, child_anchor, page.depth + 1, child_score):
            enqueued += 1


def _seed_fields(seed) -> tuple[str, str]:
    """Normalize a seed (dict or str) into (url, title)."""
    if isinstance(seed, str):
        return seed.strip(), ""
    if isinstance(seed, dict):
        url = str(seed.get("link") or seed.get("url") or "").strip()
        return url, str(seed.get("title") or "").strip()
    return "", ""


def to_content_map(pages: list[PageResult]) -> dict:
    """Adapt crawl output to the ``{url: text}`` shape that
    :func:`llm.generate_summary` and the RAG indexer consume."""
    return {p.url: (f"{p.title} - {p.text}" if p.title else p.text) for p in pages if p.text}
