"""
export.py
PDF report generation for OBSCURA investigations using reportlab Platypus.
"""

import io
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
)

# Colour palette
_RED    = colors.HexColor("#CC2222")
_DARK   = colors.HexColor("#111111")
_GRAY   = colors.HexColor("#555555")
_LGRAY  = colors.HexColor("#AAAAAA")
_WHITE  = colors.white
_OFFWHT = colors.HexColor("#F7F7F7")


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "OBSCURATitle", parent=base["Title"],
            fontSize=22, textColor=_RED, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "OBSCURASubtitle", parent=base["Normal"],
            fontSize=9, textColor=_GRAY, spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "OBSCURASection", parent=base["Heading2"],
            fontSize=13, textColor=_RED, spaceBefore=14, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "OBSCURABody", parent=base["Normal"],
            fontSize=9, textColor=_DARK, leading=14, spaceAfter=3,
        ),
        "source_link": ParagraphStyle(
            "OBSCURALink", parent=base["Normal"],
            fontSize=8, textColor=_GRAY, leading=11,
        ),
    }


# ---------------------------------------------------------------------------
# Lightweight Markdown → reportlab flowables
# ---------------------------------------------------------------------------

def _inline_md(text: str) -> str:
    """
    Convert inline Markdown to reportlab XML.
    """
    if text is None:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 1. Pull `code` spans out of the text — they're now opaque blobs that
    #    bold/italic regex can't reach into.
    code_slots: list[str] = []
    def _grab_code(m):
        code_slots.append(m.group(1))
        return f"\x00CODE{len(code_slots) - 1}\x00"
    text = re.sub(r"`([^`]+?)`", _grab_code, text)

    # 2. Bold first (greedy `**…**`), then italics. Order matters so `**`
    #    doesn't get half-eaten by a stray `*` regex.
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*",     r"<i>\1</i>", text)
    text = re.sub(r"_(.+?)_",       r"<i>\1</i>", text)

    # 3. Restore code spans as <font> tags.
    def _restore_code(m):
        idx = int(m.group(1))
        return f'<font name="Courier">{code_slots[idx]}</font>'
    text = re.sub(r"\x00CODE(\d+)\x00", _restore_code, text)
    return text


def _safe_paragraph(xml_text: str, style):
    """
    Build a Paragraph but fall back to plain-text rendering if reportlab
    rejects the inline markup.
    """
    if xml_text is None:
        xml_text = ""
    
    try:
        return Paragraph(xml_text, style)
    except Exception:
        plain = re.sub(r"<[^>]+>", "", xml_text)
        plain = (plain.replace("&amp;", "&")
                       .replace("&lt;", "<")
                       .replace("&gt;", ">"))
        plain = (plain.replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
        return Paragraph(plain, style)


def _md_to_flowables(text: str, styles: dict) -> list:
    """Convert a Markdown string to a list of reportlab flowables."""
    flowables = []
    
    # Pre-process text to remove common PDF artifacts
    text = text.strip()
    # Remove leading/trailing horizontal rules if they wrap the content
    text = re.sub(r'^[\s\n]*[-*_]{3,}[\s\n]*', '', text)
    text = re.sub(r'[\s\n]*[-*_]{3,}[\s\n]*$', '', text)

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s:
            flowables.append(Spacer(1, 4))
            i += 1
            continue

        # Handle Markdown Tables
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-\|:]+\|$", lines[i+1].strip()):
            table_data = []
            # Extract header - filter out empty strings from split but keep track of column count
            raw_headers = [c.strip() for c in s.split("|")]
            # Usually markdown tables have leading/trailing | resulting in empty first/last elements
            if raw_headers and not raw_headers[0]:
                raw_headers.pop(0)
            if raw_headers and not raw_headers[-1]:
                raw_headers.pop(-1)
            
            if not raw_headers:
                i += 1
                continue

            table_data.append([_safe_paragraph(_inline_md(h), styles["body"]) for h in raw_headers])
            num_cols = len(raw_headers)
            
            i += 2 # Skip header and separator row
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw_cells = [c.strip() for c in lines[i].split("|")]
                if raw_cells and not raw_cells[0]:
                    raw_cells.pop(0)
                if raw_cells and not raw_cells[-1]:
                    raw_cells.pop(-1)
                
                # Pad or truncate to match header column count
                if len(raw_cells) < num_cols:
                    raw_cells.extend([""] * (num_cols - len(raw_cells)))
                else:
                    raw_cells = raw_cells[:num_cols]
                
                table_data.append([_safe_paragraph(_inline_md(c), styles["body"]) for c in raw_cells])
                i += 1
            
            if table_data:
                # Calculate column widths based on header content
                header_text = "".join(raw_headers).lower()
                
                if num_cols == 4:
                    # Solutions & Defensive Recommendations
                    c_widths = [35 * mm, 40 * mm, 55 * mm, 40 * mm]
                elif num_cols == 3:
                    if "#" in header_text and "onion" in header_text:
                        # Source Links Referenced for Analysis
                        c_widths = [10 * mm, 70 * mm, 90 * mm]
                    elif "insight" in header_text:
                        # Key Insights
                        c_widths = [10 * mm, 80 * mm, 80 * mm]
                    else:
                        # Investigation Artifacts (Artifact Type, Value, Context)
                        c_widths = [45 * mm, 60 * mm, 65 * mm]
                elif num_cols == 2:
                    if "action" in header_text or "next" in header_text:
                        # Next Steps
                        c_widths = [60 * mm, 110 * mm]
                    else:
                        c_widths = [50 * mm, 120 * mm]
                else:
                    c_widths = [None] * num_cols

                t = Table(table_data, hAlign="LEFT", colWidths=c_widths)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), _OFFWHT),
                    ('TEXTCOLOR', (0, 0), (-1, 0), _DARK),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('GRID', (0, 0), (-1, -1), 0.5, _LGRAY),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))
                flowables.append(t)
                flowables.append(Spacer(1, 10))
            continue

        if s.startswith("#### "):
            flowables.append(_safe_paragraph(f"<b>{_inline_md(s[5:])}</b>", styles["body"]))
        elif s.startswith("### "):
            flowables.append(_safe_paragraph(f"<b>{_inline_md(s[4:])}</b>", styles["section"]))
        elif s.startswith("## "):
            flowables.append(_safe_paragraph(f"<b>{_inline_md(s[3:])}</b>", styles["section"]))
        elif s.startswith("# "):
            flowables.append(_safe_paragraph(f"<b>{_inline_md(s[2:])}</b>", styles["section"]))
        elif s.startswith(("- ", "* ", "+ ")):
            flowables.append(_safe_paragraph(f"&bull;&nbsp;&nbsp;{_inline_md(s[2:])}", styles["body"]))
        elif re.match(r"^\d+\.\s+", s):
            m = re.match(r"^(\d+)\.\s+(.*)", s)
            flowables.append(_safe_paragraph(f"{m.group(1)}.&nbsp;&nbsp;{_inline_md(m.group(2))}", styles["body"]))
        elif s in ("---", "***", "___"):
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=_LGRAY))
        else:
            flowables.append(_safe_paragraph(_inline_md(s), styles["body"]))
        
        i += 1

    return flowables


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_pdf(investigation: dict) -> bytes:
    """
    Build a formatted PDF report for one investigation dict.
    Returns raw PDF bytes suitable for st.download_button.
    """
    styles = _build_styles()
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"OBSCURA — {investigation.get('query', '')}",
        author="OBSCURA: AI-Powered Dark Web OSINT Tool",
    )

    story = []

    # ── Header ───────────────────────────────────────────────────────────────
    story.append(Paragraph("OBSCURA Investigation Report", styles["title"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_RED, spaceAfter=8))

    # Timestamp formatting
    ts_raw = investigation.get("timestamp", "")
    try:
        if not ts_raw:
            ts = "—"
        else:
            ts = datetime.fromisoformat(str(ts_raw)).strftime("%Y-%m-%d  %H:%M:%S")
    except Exception:
        ts = str(ts_raw) if ts_raw is not None else "—"

    # Meta table
    meta_rows = [
        ["Query",         _safe_paragraph(_inline_md(investigation.get("query") or "—"), styles["body"])],
        ["Refined Query", _safe_paragraph(_inline_md(investigation.get("refined_query") or "—"), styles["body"])],
        ["Model",         _safe_paragraph(_inline_md(investigation.get("model") or "—"), styles["body"])],
        ["Domain",        _safe_paragraph(_inline_md(investigation.get("preset") or "—"), styles["body"])],
        ["Status",        _safe_paragraph(str(investigation.get("status") or "active").capitalize(), styles["body"])],
        ["Tags",          _safe_paragraph(_inline_md(investigation.get("tags") or "—"), styles["body"])],
        ["Generated",     _safe_paragraph(ts, styles["body"])],
    ]
    meta_table = Table(meta_rows, colWidths=[38 * mm, 130 * mm], hAlign="LEFT")
    meta_table.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (0, -1), _GRAY),
        ("TEXTCOLOR",      (1, 0), (1, -1), _DARK),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_OFFWHT, _WHITE]),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("GRID",           (0, 0), (-1, -1), 0.25, _LGRAY),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # ── Sources ───────────────────────────────────────────────────────────────
    sources = investigation.get("sources", [])
    if sources:
        story.append(Paragraph("Sources", styles["section"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=_LGRAY, spaceAfter=4))
        for i, src in enumerate(sources, 1):
            title = _inline_md(src.get("title") or "Untitled")
            link  = src.get("link") or ""
            # Escape link for XML safety
            safe_link = str(link).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            display = f"{i}.&nbsp;&nbsp;<b>{title}</b>"
            if link:
                short = safe_link[:90] + ("…" if len(safe_link) > 90 else "")
                display += f"<br/><font name='Courier' size='7' color='#999999'>{short}</font>"
            
            story.append(_safe_paragraph(display, styles["source_link"]))
            story.append(Spacer(1, 2))
        story.append(Spacer(1, 6))

    # ── Findings (new page) ───────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Findings", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_LGRAY, spaceAfter=6))
    summary = investigation.get("summary", "No summary available.")
    story.extend(_md_to_flowables(summary, styles))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_LGRAY))
    story.append(Paragraph(
    "Generated by OBSCURA — AI-Powered Dark Web OSINT Tool. "
        "For lawful investigative purposes only.",
        styles["subtitle"],
    ))

    try:
        doc.build(story)
    except Exception as exc:
        # If the complex build fails, try a ultra-simplified version
        # to at least give the user something.
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        simple_story = [
            Paragraph("OBSCURA Investigation Report (Recovery Mode)", styles["title"]),
            Spacer(1, 10),
            Paragraph(f"Error during PDF generation: {str(exc)}", styles["body"]),
            Spacer(1, 10),
            Paragraph("Investigation Summary:", styles["section"]),
            Spacer(1, 5),
        ]
        # Just add plain text summary
        summary_content = investigation.get("summary", "") or "No summary available."
        plain_summary = re.sub(r"<[^>]+>", "", str(summary_content))
        simple_story.append(Paragraph(plain_summary.replace("\n", "<br/>"), styles["body"]))
        doc.build(simple_story)
        
    return buf.getvalue()