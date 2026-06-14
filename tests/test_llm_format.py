"""Characterization tests for llm._generate_final_string (pure formatting)."""
import llm
from conftest import ONION_URL


def test_final_string_strips_path_after_onion_and_numbers_rows():
    results = [{"link": f"{ONION_URL}/path?q=1", "title": "Hello, World!"}]
    out = llm._generate_final_string(results)
    assert out.startswith("1. ")
    assert ONION_URL in out          # host kept
    assert "?q=1" not in out         # everything after .onion stripped
    assert "World" in out            # punctuation-cleaned title retained


def test_final_string_skips_fully_empty_rows():
    assert llm._generate_final_string([{"link": "", "title": ""}]) == ""


def test_final_string_truncate_mode_shortens_title_and_drops_link():
    results = [{"link": ONION_URL, "title": "x" * 40}]
    out = llm._generate_final_string(results, truncate=True)
    assert "..." in out
    assert "x" * 30 in out
    assert ONION_URL not in out      # link blanked in truncate mode


def test_clean_refined_query_strips_whitespace_quotes_and_labels():
    assert llm._clean_refined_query("\n\nransomware leak\n") == "ransomware leak"
    assert llm._clean_refined_query('  "data breach forum"  ') == "data breach forum"
    assert llm._clean_refined_query("Refined Query: stolen credentials") == "stolen credentials"
    assert llm._clean_refined_query("multi   space\tquery") == "multi space query"


def test_clean_refined_query_falls_back_when_empty():
    assert llm._clean_refined_query("", fallback="original query") == "original query"
    assert llm._clean_refined_query("   \n  ", fallback="orig") == "orig"
