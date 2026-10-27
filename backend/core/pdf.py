"""Our own PDFs of a tool's result: what the page shows, as a document to keep. A title, tables in
the site's look, a footer saying where the data came from and when, and a faint "Only For
Information" watermark, since none of them is an official copy.

Helvetica (built into every PDF reader) has no Telugu letters, so text with Telugu in it (village
names, survey numbers like "1/2అ", names on Bhu Bharati) is set in Hind Guntur, which has both
scripts, and shaped by HarfBuzz (the uharfbuzz package) so its letters join as they should.
"""
import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi.responses import Response
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Table, TableStyle

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving, so no time-zone database is needed
GREEN, BEIGE, BORDER, MUTED = (colors.HexColor(c) for c in ("#1c6e4a", "#f6f1e6", "#e6e0d0", "#6b6f6c"))
MARGIN = 15 * mm

_FONTS = Path(__file__).resolve().parents[1] / "fonts"
pdfmetrics.registerFont(TTFont("HindGuntur", _FONTS / "HindGuntur-Regular.ttf", shapable=True))
pdfmetrics.registerFont(TTFont("HindGuntur-Bold", _FONTS / "HindGuntur-Bold.ttf", shapable=True))

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=16, leading=20),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10, leading=13, textColor=MUTED),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=6 * mm, spaceAfter=2 * mm),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=MUTED),
    "value": ParagraphStyle("value", fontName="Helvetica-Bold", fontSize=10, leading=12),
    "total": ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=GREEN),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=11, wordWrap="CJK"),  # long numbers may break anywhere
}
# The same styles in Hind Guntur. Telugu needs taller lines, and wrapping anywhere (CJK) would
# cut letters apart before HarfBuzz joins them, so these wrap at spaces.
_TELUGU_STYLES = {
    name: ParagraphStyle(f"{name}-te", parent=s, fontName="HindGuntur-Bold" if s.fontName.endswith("Bold") else "HindGuntur",
                         leading=round(s.fontSize * 1.5), wordWrap=None, shaping=1)
    for name, s in STYLES.items()
}
_TELUGU = re.compile("[\u0c00-\u0c7f]")
# HarfBuzz shapes each word as one script, guessed from its first letter, so Telugu after Latin
# letters in the same word ("Kokapet|కోకాపేట్") gets a space before it, to be shaped as Telugu.
# (A zero-width space isn't enough: reportlab shapes words split at plain spaces only.)
_LATIN_THEN_TELUGU = re.compile("(?<=[A-Za-z])([^\\s\u0c00-\u0c7f]*)(?=[\u0c00-\u0c7f])")


def para(text, style: str) -> Paragraph:
    """`text` in one of STYLES, "-" when there's nothing."""
    text = str(text) if text not in (None, "") else "-"
    if _TELUGU.search(text):
        return Paragraph(escape(_LATIN_THEN_TELUGU.sub("\\1 ", text)), _TELUGU_STYLES[style])
    return Paragraph(escape(text), STYLES[style])


def rupees(n) -> str:
    """Rs. with Indian grouping (1,23,456), as the pages show it; Helvetica has no ₹ sign."""
    if n is None:
        return "-"
    whole, _, frac = str(abs(n)).partition(".")
    head, groups = whole[:-3], [whole[-3:]]
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return f"{'-' if n < 0 else ''}Rs. {','.join(groups)}{'.' + frac if frac else ''}"


def cells(rows: list, widths: list, header: bool = False) -> Table:
    """A table in the page's look: beige labels (first column, or the header row), thin borders."""
    label = ((0, 0), (-1, 0)) if header else ((0, 0), (0, -1))
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("BACKGROUND", *label, BEIGE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def fields(pairs) -> Table:
    """Label/value rows, like a record on the page."""
    return cells([[para(k, "label"), para(v, "value")] for k, v in pairs], [55 * mm, 125 * mm])


def build(story: list, *, title: str, note: str, source: str, now: datetime = None, pagesize=A4) -> bytes:
    """`story` on as many pages as it takes, each with the footer (`note`, the source and when the
    PDF was made) and the watermark."""
    now = now or datetime.now(IST)
    width, height = pagesize

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 12 * mm, note)
        canvas.drawString(MARGIN, 8.4 * mm, f"Source: {source}. Made with TruDocs on {now:%d %b %Y, %H:%M} IST.")
        canvas.drawRightString(width - MARGIN, 8.4 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def watermark(canvas, doc):  # drawn last, over the page, faint enough to read through
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFillAlpha(0.16)
        canvas.setFont("Helvetica", 54)
        canvas.translate(width / 2, height / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "Only For Information")
        canvas.restoreState()

    out = io.BytesIO()
    doc = BaseDocTemplate(out, pagesize=pagesize, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=22 * mm,
                          title=title, author="TruDocs")
    doc.addPageTemplates([PageTemplate(frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")],
                                       onPage=footer, onPageEnd=watermark)])
    doc.build(story)
    return out.getvalue()


def filename(*parts) -> str:
    """A file name like "Market-value-Kokapet.pdf": ASCII only, since it travels in an HTTP header."""
    return "-".join(p for p in (re.sub(r"[^A-Za-z0-9]+", "-", str(x)).strip("-") for x in parts) if p) + ".pdf"


def response(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})
