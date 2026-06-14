"""Characterization tests for scrape.py normalization + truncation (no network)."""
import scrape
from conftest import ONION_URL


def test_normalize_url_data_trims():
    assert scrape._normalize_url_data({"link": f"  {ONION_URL} ", "title": " T "}) == (ONION_URL, "T")


def test_normalize_url_data_non_dict():
    assert scrape._normalize_url_data("not a dict") == ("", "Untitled")


def test_normalize_url_data_missing_title_defaults():
    assert scrape._normalize_url_data({"link": ONION_URL}) == (ONION_URL, "Untitled")


def test_scrape_multiple_truncates_with_suffix(monkeypatch):
    monkeypatch.setattr(scrape, "scrape_single", lambda url_data, *a, **k: (url_data["link"], "A" * 5000))
    out = scrape.scrape_multiple([{"link": ONION_URL, "title": "t"}], max_workers=1, max_return_chars=100)
    assert len(out[ONION_URL]) == 100
    assert out[ONION_URL].endswith("...(truncated)")


def test_scrape_multiple_hard_truncates_when_cap_below_suffix(monkeypatch):
    monkeypatch.setattr(scrape, "scrape_single", lambda url_data, *a, **k: (url_data["link"], "A" * 5000))
    out = scrape.scrape_multiple([{"link": ONION_URL, "title": "t"}], max_workers=1, max_return_chars=5)
    assert out[ONION_URL] == "AAAAA"


def test_scrape_multiple_ignores_non_list():
    assert scrape.scrape_multiple("nope") == {}
