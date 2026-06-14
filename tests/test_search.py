"""Characterization tests for search.py pure logic (parsers, scoring, dedup)."""
from bs4 import BeautifulSoup

import search
from conftest import ONION_URL


def test_extract_onion_href_finds_url():
    href = f"/redirect?url={ONION_URL}/path"
    assert search._extract_onion_href(href) == f"{ONION_URL}/path"


def test_extract_onion_href_none_when_absent():
    assert search._extract_onion_href("https://example.com") is None


def test_is_useful_result_rules():
    assert search._is_useful_result(ONION_URL, "Good Title") is True
    assert search._is_useful_result("", "Good Title") is False
    assert search._is_useful_result(ONION_URL, "ab") is False          # title too short
    assert search._is_useful_result(f"{ONION_URL}/search?q=x", "Title") is False  # 'search' filtered


def test_score_result_counts_distinct_terms():
    result = {"title": "Database leak forum", "link": ONION_URL}
    assert search._score_result(result, ["leak", "database", "missing"]) == 2


def test_score_and_sort_orders_by_relevance_stably():
    results = [
        {"title": "random page", "link": ONION_URL},
        {"title": "database leak", "link": ONION_URL},
    ]
    ordered = search.score_and_sort(results, "database leak")
    assert ordered[0]["title"] == "database leak"
    # internal scoring key must not leak out
    assert "_score" not in ordered[0]


def test_parse_ahmia_extracts_results():
    html = f"""
    <ul>
      <li class="result"><h4><a href="{ONION_URL}/a">First Result</a></h4></li>
      <li class="result"><h4><a href="https://clearnet.example">Skip me</a></h4></li>
    </ul>"""
    soup = BeautifulSoup(html, "html.parser")
    results = search._parse_ahmia(soup)
    assert len(results) == 1
    assert results[0]["link"] == f"{ONION_URL}/a"
    assert results[0]["title"] == "First Result"


def test_parse_generic_scans_all_anchors():
    html = f'<a href="{ONION_URL}/x">Hello World</a><a href="/local">nope</a>'
    soup = BeautifulSoup(html, "html.parser")
    results = search._parse_generic(soup)
    assert results == [{"title": "Hello World", "link": f"{ONION_URL}/x"}]


def test_get_search_results_dedups_and_sorts(monkeypatch):
    # Every engine returns the same two links; one is more relevant.
    canned = [
        {"title": "unrelated", "link": ONION_URL},
        {"title": "breach database dump", "link": f"{ONION_URL}/db"},
    ]
    monkeypatch.setattr(search, "fetch_search_results", lambda *a, **k: list(canned))
    out = search.get_search_results("database breach", max_workers=2)
    links = [r["link"] for r in out]
    assert len(links) == len(set(links))             # deduplicated
    assert out[0]["link"] == f"{ONION_URL}/db"       # most relevant first


def test_dedup_key_is_scheme_and_case_insensitive():
    host = "abcdefghij234567abcdefghij234567abcdefghij234567abcdefgh"
    assert search._dedup_key(f"http://{host}.onion") == search._dedup_key(f"https://{host}.onion/")
    assert search._dedup_key(f"HTTP://{host.upper()}.onion") == search._dedup_key(f"http://{host}.onion")


def test_get_search_results_collapses_scheme_variants(monkeypatch):
    canned = [
        {"title": "a", "link": ONION_URL},
        {"title": "b", "link": ONION_URL.replace("http://", "https://") + "/"},
    ]
    monkeypatch.setattr(search, "fetch_search_results", lambda *a, **k: list(canned))
    out = search.get_search_results("anything", max_workers=1)
    assert len(out) == 1   # http + https + trailing slash → one entry


def test_get_search_results_returns_partial_on_deadline(monkeypatch):
    """A few slow/dead engines must not stall the whole search — the deadline
    returns whatever responded in time."""
    import time
    monkeypatch.setattr(search, "SEARCH_DEADLINE", 1)
    fast = search.DEFAULT_SEARCH_ENGINES[0]

    def fake_fetch(endpoint, query, name=""):
        if endpoint == fast:
            return [{"title": "fast hit", "link": f"{ONION_URL}/fast"}]
        time.sleep(5)  # slower than the 1s deadline → abandoned
        return [{"title": "slow", "link": f"{ONION_URL}/slow"}]

    monkeypatch.setattr(search, "fetch_search_results", fake_fetch)
    start = time.time()
    out = search.get_search_results("q", max_workers=16)
    elapsed = time.time() - start
    assert elapsed < 3                                   # didn't wait for the 5s engines
    assert any("fast" in r["title"] for r in out)        # fast engine's result kept
