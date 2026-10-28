"""Our own PDFs of a tool's result: what the page shows, as a document to keep. A title, tables in
the site's look, a footer saying where the data came from and when, and a faint "Only For
Information" watermark, since none of them is an official copy.

Every PDF a tool hands out, ours or the portal's, starts with our front page (`document`): the
TruEstate cover, with the service's name and what was searched. The file is named in the same words.

Helvetica (built into every PDF reader) has no Telugu letters, so text with Telugu in it (village
names, survey numbers like "1/2అ", names on Bhu Bharati) is set in Hind Guntur, which has both
scripts, and shaped by HarfBuzz (the uharfbuzz package) so its letters join as they should.
"""
import io
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi.responses import Response
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Table, TableStyle

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving, so no time-zone database is needed
GREEN, BEIGE, BORDER, MUTED = (colors.HexColor(c) for c in ("#1c6e4a", "#f6f1e6", "#e6e0d0", "#6b6f6c"))
MARGIN = 15 * mm
log = logging.getLogger("trudocs.pdf")

_FONTS = Path(__file__).resolve().parents[1] / "fonts"
pdfmetrics.registerFont(TTFont("HindGuntur", _FONTS / "HindGuntur-Regular.ttf", shapable=True))
pdfmetrics.registerFont(TTFont("HindGuntur-Bold", _FONTS / "HindGuntur-Bold.ttf", shapable=True))
# The front page's, as on the TruEstate cover: Poppins for its words, Montserrat for the logo's.
pdfmetrics.registerFont(TTFont("Poppins-Bold", _FONTS / "Poppins-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Poppins-SemiBold", _FONTS / "Poppins-SemiBold.ttf"))
pdfmetrics.registerFont(TTFont("Montserrat-Bold", _FONTS / "Montserrat-Bold.ttf"))

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=16, leading=20),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10, leading=13, textColor=MUTED),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=6 * mm, spaceAfter=2 * mm),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=MUTED),
    "value": ParagraphStyle("value", fontName="Helvetica-Bold", fontSize=10, leading=12),
    "total": ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=GREEN),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=11, wordWrap="CJK"),  # long numbers may break anywhere
    # what was searched, on the front page (its size in the front page's units, see _cover)
    "cover": ParagraphStyle("cover", fontName="Poppins-SemiBold", fontSize=44, leading=57, textColor=colors.HexColor("#163a2e")),
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


# The front page: the TruEstate cover of the Karnataka tools, redrawn from it. The logo at the top
# left, diamonds fading out down the left edge, the document's name large at the bottom left and
# faint down the right edge, what was searched above the name. It's drawn in the cover's own units
# (a landscape A4 page is 1403.2 x 992.4 of them), scaled to the document's first page, so an A4
# certificate gets a portrait cover and an A3 map an A3 one.
_COVER_SHORT_SIDE = 992.4
# shortcut: 4 PDFs get their front page at a time, site-wide, since each holds a few copies of
# itself meanwhile (an 18 MB 22-A list, ~60 MB) and the server has 1 GiB; more with more memory.
_COVERING = threading.BoundedSemaphore(4)
# The logo's two shapes, a roof and a house with an arrow up its middle, in the pixels of the site's
# logo (35 x 44) they were traced from. Their left halves are lighter.
_LOGO_ROOF = ((0.5, 10.5), (17.5, 1), (34.5, 10.5), (34.5, 18), (17.5, 8.5), (0.5, 18))
_LOGO_HOUSE = ((17.5, 16), (34.5, 25.5), (34.5, 37), (26.75, 37), (26.75, 29.6), (21.25, 26.5), (21.25, 44.5),
               (13.75, 44.5), (13.75, 26.5), (8.25, 29.6), (8.25, 37), (0.5, 37), (0.5, 25.5))


def _cover(title: str, subject: str, page_w: float, page_h: float) -> bytes:
    scale = min(page_w, page_h) / _COVER_SHORT_SIDE
    w, h = page_w / scale, page_h / scale
    out = io.BytesIO()
    c = Canvas(out, pagesize=(page_w, page_h))
    c.scale(scale, scale)
    c.setFillColor(colors.HexColor("#f9f9f9"))
    c.rect(0, 0, w, h, stroke=0, fill=1)

    c.saveState()  # the diamonds, a little fainter each column, gone by x = 352
    edge = c.beginPath()
    edge.rect(0, 0, 352, h)
    c.clipPath(edge, stroke=0, fill=0)
    c.setLineWidth(2.2)
    for col in range(6):
        x = 14.5 + 64 * col
        grey = (249 - 14 * (1 - x / 360)) / 255
        c.setStrokeColorRGB(grey, grey, grey)
        for row in range(int(h // 63) + 2):
            c.saveState()
            c.translate(x, h - 23.5 - 63 * row)
            c.rotate(45)
            c.roundRect(-20.75, -20.75, 41.5, 41.5, 11.5, stroke=1, fill=0)
            c.restoreState()
    c.restoreState()

    c.saveState()  # the name down the right edge, running off the page
    c.setFillColor(colors.HexColor("#dadada"))
    c.setFont("Poppins-Bold", 198)
    c.translate(w - 207, h - 51.7)
    c.rotate(-90)
    c.drawString(0, 0, title)
    c.restoreState()

    for shape in (_LOGO_ROOF, _LOGO_HOUSE):
        path = c.beginPath()
        path.moveTo(63.6 + 1.15 * shape[0][0], h - 86.65 - 1.15 * shape[0][1])
        for x, y in shape[1:]:
            path.lineTo(63.6 + 1.15 * x, h - 86.65 - 1.15 * y)
        path.close()
        c.setFillColor(colors.HexColor("#162a29"))
        c.drawPath(path, stroke=0, fill=1)
        c.saveState()
        left = c.beginPath()
        left.rect(63.6, h - 150, 1.15 * 17.5, 70)
        c.clipPath(left, stroke=0, fill=0)
        c.setFillColor(colors.HexColor("#203c3b"))
        c.drawPath(path, stroke=0, fill=1)
        c.restoreState()
    c.setFillColor(colors.HexColor("#1f2422"))
    c.setFont("Montserrat-Bold", 36.3)
    c.drawString(121.3, h - 126, "TruEstate")

    # The name, bottom-up from its last line, kept clear of the faint one on the right.
    lines = simpleSplit(title, "Poppins-Bold", 100, w - 360)
    c.setFillColor(colors.black)
    c.setFont("Poppins-Bold", 100)
    for n, line in enumerate(reversed(lines)):
        c.drawString(64, 105.2 + 130 * n, line)
    if subject:
        p = para(subject, "cover")
        p.wrap(w - 360, h)
        top_of_name = 105.2 + 130 * (len(lines) - 1) + 70.2
        p.drawOn(c, 64, top_of_name + 64 - (p.style.leading - p.style.fontSize))  # its last line 64 above the name
    c.showPage()
    c.save()
    return out.getvalue()


def with_cover(content: bytes, title: str, subject: str) -> bytes:
    """`content` with our front page first, the size of its first page. A PDF its department signed
    (TG-RERA's certificates) goes out as issued, since an added page would break the signature,
    and so does one locked with a password."""
    try:
        with _COVERING:
            doc = PdfReader(io.BytesIO(content))
            if doc.is_encrypted or any(f.get("/FT") == "/Sig" and f.get("/V") for f in (doc.get_fields() or {}).values()):
                return content
            first = doc.pages[0]
            page_w, page_h = float(first.cropbox.width), float(first.cropbox.height)
            if first.rotation % 180:
                page_w, page_h = page_h, page_w
            book = PdfWriter(clone_from=doc)
            book.insert_page(PdfReader(io.BytesIO(_cover(title, subject, page_w, page_h))).pages[0], 0)
            out = io.BytesIO()
            book.write(out)
            return out.getvalue()
    except Exception as exc:  # a PDF pypdf can't read still goes out, only without the front page
        log.warning("no front page for a %s PDF: %s", title, type(exc).__name__)
        return content


def document(content: bytes, title: str, *searched) -> tuple:
    """(the PDF with our front page, its file name): the service's name and what was searched, on the
    front page and in the name, e.g. "Land Details Search - Hydersaipet - Survey No. 1.pdf"."""
    searched = [" ".join(str(s).split()) for s in searched if s and str(s).strip()]
    return with_cover(content, title, " · ".join(searched)), filename(title, *searched)  # a line never starts with "·"


def filename(*parts) -> str:
    """A file name like "Land Market Value - Kokapet - Gandipet mandal.pdf": ASCII only, since it
    travels in an HTTP header, so Telugu letters are left out ("1/2అ" → "1-2")."""
    words = (" ".join(re.sub(r"[^A-Za-z0-9 ().,&'_-]+", " ", str(p).replace("/", "-")).split()).strip(" -") for p in parts)
    return " - ".join(w for w in words if w)[:150].rstrip(" -") + ".pdf"


def response(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})
