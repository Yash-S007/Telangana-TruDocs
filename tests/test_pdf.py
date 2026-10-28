"""The shared PDF builder: our own PDFs of a tool's result, and the front page on every PDF."""
import io
import re

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab import rl_config
from reportlab.lib.pagesizes import A4, landscape
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
    assert pdf.filename("Land Details Search", "Kokapet|కోకాపేట్", "Survey No. 1/2అ") == "Land Details Search - Kokapet - Survey No. 1-2.pdf"
    assert pdf.filename("Land Market Value", "", "BANJARA HILLS (PART)") == "Land Market Value - BANJARA HILLS (PART).pdf"
    assert pdf.filename("RERA Certificate", 'A "quoted"\r\nname;') == "RERA Certificate - A quoted name.pdf"  # nothing that breaks the header
    assert len(pdf.filename("Village Map", "x" * 400)) == 154


def _official(*, rotate=0, signed=False) -> bytes:
    """A one-page landscape PDF as a department might send it, optionally signed."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R%s >>" % (b" /AcroForm << /Fields [4 0 R] >>" if signed else b""),
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Rotate %d >>" % rotate,
               b"<< /FT /Sig /T (Signature1) /V << /Type /Sig >> >>"]
    out, offsets = b"%PDF-1.7\n", []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj %s endobj\n" % (n, obj)
    table = b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"xref\n0 5\n0000000000 65535 f \n%strailer << /Size 5 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (table, len(out))


def test_the_front_page_comes_first_and_names_the_search(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    body = pdf.build([pdf.para("A title", "title")], title="Doc title", note="n", source="s", pagesize=landscape(A4))
    content, name = pdf.document(body, "Survey Map", " Kokapet ", "", None, "Survey No. 12/అ")
    assert name == "Survey Map - Kokapet - Survey No. 12.pdf"
    doc = PdfReader(io.BytesIO(content))
    cover, page = doc.pages
    assert (cover.mediabox.width, cover.mediabox.height) == (page.mediabox.width, page.mediabox.height)  # landscape like it
    words = cover.extract_text()
    assert "TruEstate" in words and "Survey Map" in words and "Kokapet" in words
    assert b"(A title)" in content and doc.metadata.title == "Doc title"  # the document itself is untouched
    assert b"HindGuntur" in content  # the Telugu in the survey number


def test_the_front_page_takes_the_shape_of_a_turned_page():
    content = pdf.with_cover(_official(rotate=90), "Village Map", "Kokapet")
    cover, page = PdfReader(io.BytesIO(content)).pages
    assert (cover.mediabox.width, cover.mediabox.height) == (595, 842) and page.rotation == 90


def test_signed_locked_and_broken_pdfs_go_out_as_issued():
    signed = _official(signed=True)
    assert pdf.with_cover(signed, "RERA Certificate", "Sample Heights") == signed
    book = PdfWriter(clone_from=PdfReader(io.BytesIO(_official())))
    book.encrypt(user_password="", owner_password="department", algorithm="AES-128")  # opens, but locked
    locked = io.BytesIO()
    book.write(locked)
    assert pdf.with_cover(locked.getvalue(), "Building Permission (TG-bPASS)", "File No. 1") == locked.getvalue()
    assert pdf.document(b"%PDF-1.4 not really", "Hydra FTL Map", "Sample Cheruvu") == (b"%PDF-1.4 not really", "Hydra FTL Map - Sample Cheruvu.pdf")
    assert len(PdfReader(io.BytesIO(pdf.with_cover(_official(), "Village Map", ""))).pages) == 2  # nothing searched: just the name


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
