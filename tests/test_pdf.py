"""The shared PDF builder: our own PDFs of a tool's result."""
import re

import pytest
from reportlab import rl_config
from reportlab.pdfbase import pdfmetrics

from backend.core import pdf


def pages(content: bytes) -> int:
    return len(re.findall(rb"/Type /Page[^s]", content))


@pytest.mark.parametrize("amount, text", [(0, "Rs. 0"), (999, "Rs. 999"), (1534, "Rs. 1,534"), (123456, "Rs. 1,23,456"),
                                          (12345678, "Rs. 1,23,45,678"), (1534.5, "Rs. 1,534.5"), (-250, "-Rs. 250"), (None, "-")])
def test_rupees_use_indian_grouping_like_the_page(amount, text):
    assert pdf.rupees(amount) == text


def test_telugu_is_shaped():
    # Without uharfbuzz, reportlab quietly skips shaping and Telugu letters come out broken.
    assert pdfmetrics.getFont("HindGuntur").shapable and pdfmetrics.getFont("HindGuntur-Bold").shapable


def test_text_with_telugu_gets_the_telugu_font():
    assert pdf.para("Kokapet", "value").style.fontName == "Helvetica-Bold"
    for text in ("1/2అ", "శ్రీనివాస్", "Gandipet | గండిపేట్"):
        style = pdf.para(text, "value").style
        assert style.fontName == "HindGuntur-Bold" and style.shaping and style.leading == 15, text
    assert pdf.para("ఎకరాలు", "cell").style.fontName == "HindGuntur" and pdf.para("ఎకరాలు", "cell").style.wordWrap is None
    assert pdf.para(None, "cell").text == "-" and pdf.para("", "cell").text == "-" and pdf.para(0, "cell").text == "0"
    assert pdf.para("A & B <c>", "cell").text == "A &amp; B &lt;c&gt;"


@pytest.mark.parametrize("text, shown", [
    ("Kokapet|కోకాపేట్", "Kokapet| కోకాపేట్"),  # else HarfBuzz would shape the Telugu as Latin
    ("Ankapoor | అంకాపూర్", "Ankapoor | అంకాపూర్"),
    ("1/2అ", "1/2అ"),
    ("12/ు", "12/ు"),
    ("అ1B", "అ1B"),
])
def test_telugu_after_latin_letters_starts_its_own_word(text, shown):
    assert pdf.para(text, "cell").text == shown


def test_filenames_are_ascii():
    assert pdf.filename("Land-details", "Kokapet|కోకాపేట్", "1/2అ") == "Land-details-Kokapet-1-2.pdf"
    assert pdf.filename("Market-value", "", "BANJARA HILLS (PART)") == "Market-value-BANJARA-HILLS-PART.pdf"


def test_every_page_has_the_footer_and_watermark(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    rows = [[pdf.para(f"row {n}", "cell"), pdf.para("గండిపేట్", "cell")] for n in range(120)]
    content = pdf.build([pdf.para("A title", "title"), pdf.cells(rows, [60, 120])], title="Doc title", note="For reference only.",
                        source="example.gov.in")
    n = pages(content)
    assert content.startswith(b"%PDF-") and n >= 2 and b"(Doc title)" in content
    assert content.count(b"(Only For Information)") == n and content.count(b"(For reference only.)") == n
    assert content.count(b"(Source: example.gov.in. Made with TruDocs on ") == n and b"(Page 2)" in content
    assert b"HindGuntur" in content  # the Telugu font is embedded


def test_response_serves_the_pdf_inline():
    r = pdf.response(b"%PDF-1.4", "Land-details-1.pdf")
    assert r.media_type == "application/pdf" and r.headers["content-disposition"] == 'inline; filename="Land-details-1.pdf"'
