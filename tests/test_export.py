"""Characterization tests for export.py markdown→PDF helpers (pure, no I/O)."""
import export
from reportlab.platypus import Table
from conftest import ONION_URL


def test_inline_md_bold_italic_code():
    assert export._inline_md("**b**") == "<b>b</b>"
    assert export._inline_md("*i*") == "<i>i</i>"
    assert export._inline_md("`c`") == '<font name="Courier">c</font>'


def test_inline_md_escapes_xml_specials():
    assert export._inline_md("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def test_inline_md_none_is_empty():
    assert export._inline_md(None) == ""


def test_md_to_flowables_builds_a_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    flowables = export._md_to_flowables(md, export._build_styles())
    assert any(isinstance(f, Table) for f in flowables)


def test_generate_pdf_returns_pdf_bytes():
    inv = {
        "query": "test query",
        "refined_query": "test",
        "model": "gpt-4.1",
        "preset": "threat_intel",
        "summary": "# Findings\n\nSome **bold** text.\n\n| Col | Val |\n|---|---|\n| a | b |",
        "sources": [{"title": "Source", "link": ONION_URL}],
        "timestamp": "2026-06-10T12:00:00",
    }
    pdf = export.generate_pdf(inv)
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000
