"""Unit tests for deep_search.py — scoring, link extraction, frontier ordering,
and the best-first crawl traversal. No network/Tor: ``fetch`` is faked."""
import deep_search
from deep_search import PageResult, deep_crawl


def _host(letter: str) -> str:
    """A syntactically valid 56-char v3 onion host (chars in [a-z2-7])."""
    return (letter * 56)[:56]


def url(letter: str, path: str = "") -> str:
    return f"http://{_host(letter)}.onion{path}"


# ── scoring ──────────────────────────────────────────────────────────────────

def test_query_terms_drops_short_tokens_and_lowercases():
    assert deep_search.query_terms("Ransomware AS a Service!!") == ["ransomware", "service"]


def test_relevance_score_counts_distinct_terms():
    terms = ["leak", "database", "missing"]
    assert deep_search.relevance_score("Database LEAK dump", terms) == 2.0
    assert deep_search.relevance_score("", terms) == 0.0


def test_link_score_weights_anchor_above_url():
    terms = ["market"]
    anchor_hit = deep_search._link_score(url("a"), "market listings", terms)
    url_only = deep_search._link_score(url("a") + "/market", "", terms)
    assert anchor_hit > url_only  # anchor weighted x2


# ── link extraction ────────────────────────────────────────────────────────

def test_extract_links_keeps_only_onion_and_dedups():
    html = f"""
      <a href="{url('a', '/x')}">Alpha</a>
      <a href="https://clearweb.com">nope</a>
      <a href="{url('a', '/x')}">dup</a>
      <a href="{url('b')}">Beta</a>
    """
    links = deep_search.extract_links(html)
    found = {u for u, _ in links}
    assert found == {url("a", "/x"), url("b")}
    assert ("https://clearweb.com" not in found)


def test_extract_links_resolves_relative_against_base():
    base = url("a")
    links = deep_search.extract_links('<a href="/deep/page">go</a>', base_url=base)
    # urljoin keeps the onion host from the base
    assert links and links[0][0].startswith(base)


# ── frontier ─────────────────────────────────────────────────────────────────

def test_frontier_pops_highest_score_first_and_dedups():
    f = deep_search._Frontier()
    assert f.push(url("a"), "", 0, 1.0) is True
    assert f.push(url("b"), "", 0, 5.0) is True
    assert f.push(url("a"), "", 0, 9.0) is False  # already enqueued
    first, *_ = f.pop()
    assert first == url("b")  # higher score wins


# ── deep_crawl traversal ─────────────────────────────────────────────────────

def _graph_fetch(graph):
    """Build a fake fetch from {url: (text, [child_urls])}."""
    def fetch(u, title_hint=""):
        if u not in graph:
            return PageResult(url=u, title=title_hint, error="404")
        text, children = graph[u]
        return PageResult(
            url=u, title=title_hint, text=text,
            links=[(c, "child") for c in children], success=True,
        )
    return fetch


def test_deep_crawl_follows_links_to_max_depth():
    a, b, c = url("a"), url("b"), url("c")
    graph = {a: ("market alpha", [b]), b: ("market beta", [c]), c: ("market gamma", [])}
    pages = deep_crawl(
        [{"link": a, "title": "seed"}], "market", fetch=_graph_fetch(graph),
        max_depth=1, max_pages=10, min_link_score=0,
    )
    urls = {p.url for p in pages}
    assert a in urls and b in urls   # depth 0 and 1 reached
    assert c not in urls             # depth 2 is beyond max_depth=1


def test_deep_crawl_respects_page_budget():
    seeds = [url(x) for x in "abcde"]
    graph = {u: ("market", []) for u in seeds}
    pages = deep_crawl(
        [{"link": u} for u in seeds], "market", fetch=_graph_fetch(graph),
        max_depth=0, max_pages=3, min_link_score=0,
    )
    assert len(pages) == 3  # hard budget enforced


def test_deep_crawl_skips_failed_and_dedups_diamond():
    # Diamond: a→{b,c}, b→d, c→d. d must be fetched once despite two parents.
    a, b, c, d = (url(x) for x in "abcd")
    graph = {
        a: ("market top", [b, c]),
        b: ("market left", [d]),
        c: ("market right", [d]),
        d: ("market bottom", []),
    }
    pages = deep_crawl(
        [{"link": a}], "market", fetch=_graph_fetch(graph),
        max_depth=3, max_pages=20, min_link_score=0,
    )
    urls = [p.url for p in pages]
    assert urls.count(d) == 1
    assert set(urls) == {a, b, c, d}


def test_deep_crawl_results_sorted_by_score_desc():
    a, b = url("a"), url("b")
    # b mentions more query terms than a → must rank first.
    graph = {a: ("ransomware", [b]), b: ("ransomware malware leak", [])}
    pages = deep_crawl(
        [{"link": a}], "ransomware malware leak", fetch=_graph_fetch(graph),
        max_depth=1, max_pages=10, min_link_score=0,
    )
    assert [p.url for p in pages] == [b, a]


def test_to_content_map_shape():
    pages = [PageResult(url=url("a"), title="T", text="body", success=True)]
    assert deep_search.to_content_map(pages) == {url("a"): "T - body"}
