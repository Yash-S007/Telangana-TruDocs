"""CDMA Tax Receipt tests. Synthetic pages shaped like the portal's (made-up owners, PTINs and
receipt numbers, no real records); the portal itself is faked."""
import json
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab import rl_config

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.routers import cdma_tax as cdma_tax_router
from backend.scrapers.cdma_tax import client

PTIN = "1113999001"
NO_RECORDS = '<form><strong><font color="red">Sorry No Records found</font></strong></form>'


def receipt_row(n, receipt_no, slno, date, paid_from, paid_to, mode, amount, link_no=None):
    return (f'<tr><td>{n}<input type="hidden" id="hdnSNO" value="{slno}" /><input type="hidden" id="hdnRECPTIN" value="{PTIN}" /></td>'
            f"<td>{PTIN}</td><td>{date}</td><td>{paid_from}</td><td>{paid_to}</td><td> {receipt_no} </td><td>{mode}</td><td>{amount}</td>"
            f"""<td><a class="btn" href="javascript:DownloadPDF('{link_no or receipt_no}   ','{slno}')"><i></i> Download</a></td></tr>""")


def receipts_page(*rows):
    heads = "".join(f"<th>{h}</th>" for h in ("Sl No", "PTIN NO", "Receipt Date", "Paid From", "Paid To", "Receipt No.", "Payment Gateway", "Amount", "Action"))
    return f'<form><table id="tblPrintRecipt" class="table"><thead><tr>{heads}</tr></thead><tbody>{"".join(rows)}</tbody></table></form>'


RECEIPTS = receipts_page(
    receipt_row(1, "190924000000000000001", "111320240919000001", "19/09/2024", "2023-2024-1", "2024-2025-2", "CASH", "1200"),
    receipt_row(2, "043700", "11130000000001", "12/03/2018", "2084-2085-1", "2084-2085-2", "CASH", "950"),
)


def money_row(label, value):
    return (f'<tr><td align="right">{label}(<i class="fa fa-inr"></i>)</td><td>:</td>'
            f'<td align="right"><label for="">{value}</label></td></tr>')


DETAILS = (
    '<table class="ghmc_table"><thead><tr><th colspan="4">i) Property Tax Details</th></tr></thead><tbody>'
    f'<tr><td>PTIN NO</td><td colspan="3">: <strong><label for="">{PTIN}</label></strong><input id="hdnPTNO" type="hidden" value="{PTIN}" /></td></tr>'
    '<tr><td>Name</td><td colspan="3">: <strong>SAMPLE OWNER   (S/O (or) D/O (or) W/O) TEST PARENT  </strong></td></tr>'
    '<tr><td>Door Number</td><td>:<strong>9-9-99 </strong></td><td>Locality</td><td>: <strong><label for="Sample Nagar">Sample Nagar</label></strong></td></tr>'
    '<tr><td>ULB</td><td>: <strong>Siddipet Municipality</strong></td><td>Usage Type</td><td>: <strong>Residential</strong></td></tr>'
    '</tbody></table>'
    '<div><strong>ii) Property Tax Due as on - <label for="">22/10/2026</label></strong></div>'
    '<table id="demoGrid"><thead><tr><th>Select</th><th>Tax Details</th><th>Demand Year</th><th>Tax Amount</th><th>Interest</th><th>Total</th><th>Payment Status</th></tr></thead>'
    '<tbody><tr><td><input type="checkbox" /></td><td>Arrear Tax</td><td>2025-2026-2</td><td>500</td><td>40</td><td>540</td><td>Due</td></tr></tbody></table>'
    '<table><tbody><tr><td>Adjustment Amount from Previous Years(<i></i>) Tax Shown below is after Deducting of Adjustment Amount.</td><td>:</td><td>0</td></tr>'
    + money_row("Arrear Tax", 500) + money_row("Arrear Interest", 40) + money_row("Current Tax", 600) + money_row("Current Interest", 0)
    + money_row("Cheque Bounce Penalty", 0) + money_row("Deviation Penalty", 0)
    + '<tr><td>Total Amount to Pay(<i class="fa fa-inr"></i>)</td><td>:</td><td><div><label id="lblAmounttoPay">1140</label></div>'
    '<label style="display:none">1140</label></td></tr></tbody></table>'
)


def search_page(*rows):
    body = "".join(f"<tr><td>{p}</td><td>{loc}</td><td>{owner}</td><td>{door}</td>"
                   f'<td><a href="javascript:ViewPTDetailsBYAsmnt({p})">View Details</a></td></tr>' for p, loc, owner, door in rows)
    return ('<form><table id="demoGrid" class="table"><thead><tr><th>PT Number</th><th>Locality Name</th><th>Owner Name</th>'
            f"<th>Door Number</th><th>Action</th></tr></thead><tbody>{body}</tbody></table></form>")


QR = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"


def receipt_page(ptin=PTIN, qr=True):
    grid = (f'<div align="right"><strong>Print On : <span>22-10-2026 11:40:12</span></strong></div>'
            f'<table border="1"><tbody><tr><td>PTIN(Property Tax Identification Number)</td><td colspan="1">{ptin}</td></tr>'
            "<tr><td>Owner Name</td><td>SAMPLE OWNER</td></tr></tbody></table>") if ptin else '<table border="1"><tbody></tbody></table>'
    qr_input = f'<input type="hidden" name="qrFilePath" value="{QR}" />' if qr else ""
    return (f'<!DOCTYPE html><html><body id="PDFtbleBody">\n <div id="Grid">\n{grid}\n </div>\n <br />\n <br />\n'
            f'<form action="/CDMA_ARBS/CDMA_PG/Download" method="post"> {qr_input}<input type="hidden" name="GridHtml" /></form>'
            "<script>$('#btnSubmit').trigger('click');</script></body></html>")


PDF = b"%PDF-1.4 synthetic receipt"


class Reply:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content or text.encode(), status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("portal error", request=httpx.Request("POST", "https://x"), response=httpx.Response(self.status_code))


class FakePortal:
    """Stands in for httpx.Client: answers each portal path from `pages`."""

    def __init__(self, pages=None, delay=0.0):
        self.pages = {"/GetReciptDetails": RECEIPTS, "/GetPTDetails_PV": DETAILS, "/BindPTSearchDetail_PV": NO_RECORDS,
                      "/GetPTForDownload": receipt_page(), "/Download": PDF, **(pages or {})}
        self.delay, self.calls = delay, []

    def __call__(self, timeout=60.0):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, path, content=None, headers=None, data=None):
        self.calls.append((path, json.loads(content) if content else data))
        time.sleep(self.delay)
        page = self.pages[path]
        if isinstance(page, Exception):
            raise page
        return Reply(content=page) if isinstance(page, bytes) else Reply(page)

    def paths(self):
        return [p for p, _ in self.calls]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    client._lookup.cache_clear()
    client._receipt_pdf.cache_clear()
    monkeypatch.setattr(client._throttle, "min_interval_seconds", 0)
    yield
    client._lookup.cache_clear()
    client._receipt_pdf.cache_clear()


def portal(monkeypatch, **kw):
    fake = FakePortal(**kw)
    monkeypatch.setattr(client, "_client", fake)
    return fake


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as exc:
        fn(*args, **kwargs)
    assert exc.value.user_message == user_message


def _app():
    app = FastAPI()
    app.include_router(cdma_tax_router.router)
    return TestClient(app)


def test_lookup_gives_owner_address_dues_and_receipts(monkeypatch):
    fake = portal(monkeypatch)
    r = client.fetch_property(f" {PTIN} ")
    assert r["ptin"] == PTIN and r["found"]
    assert r["property"] == {"owner": "SAMPLE OWNER", "door_no": "9-9-99", "locality": "Sample Nagar",
                             "town": "Siddipet Municipality", "usage": "Residential"}
    assert r["dues"] == {"as_on": "22/10/2026", "arrear_tax": 500, "arrear_interest": 40, "current_tax": 600, "current_interest": 0,
                         "cheque_bounce_penalty": 0, "deviation_penalty": 0, "adjustment": 0, "total": 1140}
    assert r["receipts"][0] == {"date": "19/09/2024", "paid_from": "2023-2024-1", "paid_to": "2024-2025-2",
                                "receipt_no": "190924000000000000001", "mode": "CASH", "amount": 1200, "slno": "111320240919000001"}
    assert r["receipts"][1]["paid_from"] == "2084-2085-1"  # the portal's own (odd) periods, shown as they are
    assert fake.calls == [("/GetReciptDetails", {"PTNO": PTIN}), ("/GetPTDetails_PV", {"PTNO": PTIN})]


def test_a_property_without_receipts_still_shows_its_dues(monkeypatch):
    portal(monkeypatch, pages={"/GetReciptDetails": NO_RECORDS})
    r = client.fetch_property(PTIN)
    assert r["receipts"] == [] and r["dues"]["total"] == 1140


def test_receipts_without_property_details_are_still_shown(monkeypatch):
    portal(monkeypatch, pages={"/GetPTDetails_PV": NO_RECORDS})
    r = client.fetch_property(PTIN)
    assert r["property"] is None and r["dues"] is None and len(r["receipts"]) == 2


def test_a_receipt_whose_download_link_doesnt_match_gets_no_pdf_link(monkeypatch):
    portal(monkeypatch, pages={"/GetReciptDetails": receipts_page(
        receipt_row(1, "190924000000000000001", "111320240919000001", "19/09/2024", "2023-2024-1", "2024-2025-2", "CASH", "1200", link_no="999"))})
    assert client.fetch_property(PTIN)["receipts"][0]["slno"] == ""


def test_unknown_ptin_and_unexpected_pages(monkeypatch):
    portal(monkeypatch, pages={"/GetReciptDetails": NO_RECORDS, "/GetPTDetails_PV": NO_RECORDS})
    _raises(NOT_FOUND, client.fetch_property, PTIN)
    for pages in ({"/GetReciptDetails": "<html>Service Unavailable</html>"}, {"/GetPTDetails_PV": "<html>Service Unavailable</html>"}):
        client._lookup.cache_clear()
        portal(monkeypatch, pages=pages)
        _raises(PORTAL_DOWN, client.fetch_property, PTIN)


def test_portal_timeouts_and_errors_are_friendly(monkeypatch):
    portal(monkeypatch, pages={"/GetReciptDetails": httpx.ReadTimeout("slow")})
    _raises(PORTAL_TIMEOUT, client.fetch_property, PTIN)
    portal(monkeypatch, pages={"/GetReciptDetails": httpx.ConnectError("down")})
    _raises(PORTAL_DOWN, client.fetch_property, PTIN)


def test_a_dropped_connection_is_tried_once_more(monkeypatch):
    # the portal sometimes closes a new connection mid-handshake (seen live: SSL EOF after 15 s)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    server.settimeout(5)
    accepted = []

    def drop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            accepted.append(1)
            conn.close()

    threading.Thread(target=drop, daemon=True).start()
    monkeypatch.setattr(client, "BASE_URL", f"https://127.0.0.1:{server.getsockname()[1]}")
    try:
        _raises(PORTAL_DOWN, client.fetch_property, PTIN)
    finally:
        server.close()
    assert len(accepted) == 2


@pytest.mark.parametrize("bad", ["", "111399900", "11139990011", "1113-99900", "ABCDEFGHIJ", "1113999001;"])
def test_bad_ptins_never_reach_the_portal(monkeypatch, bad):
    fake = portal(monkeypatch)
    _raises(BAD_INPUT, client.fetch_property, bad)
    assert fake.calls == []


def test_a_lookup_is_reused_and_identical_lookups_share_one_fetch(monkeypatch):
    fake = portal(monkeypatch, delay=0.2)
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda _: client.fetch_property(PTIN), range(5)))
    assert all(r == results[0] for r in results)
    client.fetch_property(PTIN)
    assert fake.paths() == ["/GetReciptDetails", "/GetPTDetails_PV"]


def test_find_by_owner_or_door_number(monkeypatch):
    fake = portal(monkeypatch, pages={"/BindPTSearchDetail_PV": search_page(
        ("1113999001", "Sample Nagar", "SAMPLE OWNER . ", "9-9-99"), ("1113999002", "Test Colony", "TEST OWNER", "9-9-98"))})
    r = client.find_properties("1113", owner_name="  sample   owner ")
    assert (r["total"], r["shown"]) == (2, 2)
    assert r["properties"][0] == {"ptin": "1113999001", "owner": "SAMPLE OWNER", "door_no": "9-9-99", "locality": "Sample Nagar"}
    client.find_properties("1113", door_no="9-9-99")
    # the portal's search takes "district,ptin,owner,door,town"; Siddipet Municipality (1113) is in district 130
    assert [b for _, b in fake.calls] == [{"Param": "130,,sample owner,,1113"}, {"Param": "130,,,9-9-99,1113"}]


def test_find_shows_at_most_100_properties(monkeypatch):
    rows = [(f"1113{n:06d}", "Sample Nagar", "SAMPLE OWNER", f"1-{n}") for n in range(250)]
    portal(monkeypatch, pages={"/BindPTSearchDetail_PV": search_page(*rows)})
    r = client.find_properties("1113", owner_name="SAMPLE")
    assert (r["total"], r["shown"], len(r["properties"])) == (250, 100, 100)


def test_find_nothing_and_unexpected_pages(monkeypatch):
    portal(monkeypatch)
    _raises(NOT_FOUND, client.find_properties, "1113", owner_name="Nobody Like This")
    portal(monkeypatch, pages={"/BindPTSearchDetail_PV": "<html>Runtime Error</html>"})
    _raises(PORTAL_DOWN, client.find_properties, "1113", owner_name="SAMPLE")


@pytest.mark.parametrize("town, door, owner", [
    ("9999", "", "SAMPLE"),     # not a CDMA town
    ("", "", "SAMPLE"),
    ("1113", "", ""),           # neither field
    ("1113", "", "AB"),         # too short: one or two letters match tens of thousands
    ("1113", "1", ""),
    ("1113", "", "SAMPLE,1113"),  # a comma would shift the portal's comma-joined fields
    ("1113", "9-9,99", ""),
    ("1113", "", 'SAMPLE"}'),
    ("1113", "", "OWNER123"),
])
def test_bad_searches_never_reach_the_portal(monkeypatch, town, door, owner):
    fake = portal(monkeypatch)
    _raises(BAD_INPUT, client.find_properties, town, door, owner)
    assert fake.calls == []


def test_towns_list_covers_every_cdma_district():
    towns = client.towns()
    assert len(towns) == 32 and sum(len(d["towns"]) for d in towns) >= 130
    assert {"id": 1113, "name": "Siddipet Municipality"} in next(d for d in towns if d["district"] == "Siddipet")["towns"]


def test_receipt_pdf_is_the_portals_own(monkeypatch):
    fake = portal(monkeypatch)
    pdf, name = client.fetch_receipt_pdf(PTIN, "190924000000000000001", "111320240919000001")
    assert pdf == PDF and name == f"CDMA-tax-receipt-{PTIN}-190924000000000000001.pdf"
    (p1, b1), (p2, form) = fake.calls
    assert (p1, b1) == ("/GetPTForDownload", {"MID": "190924000000000000001", "PTINNO": PTIN, "SLNO": "111320240919000001"})
    # what the receipt page's own script posts: the Grid's inner HTML and the QR code
    assert p2 == "/Download" and form["qrFilePath"] == QR
    assert form["GridHtml"].lstrip().startswith('<div align="right"><strong>Print On') and form["GridHtml"].rstrip().endswith("</table>")
    client.fetch_receipt_pdf(PTIN, "190924000000000000001", "111320240919000001")
    assert len(fake.calls) == 2  # repeats come from the cache


def test_identical_receipt_downloads_share_one_build(monkeypatch):
    fake = portal(monkeypatch, delay=0.2)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: client.fetch_receipt_pdf(PTIN, "043700", "11130000000001"), range(4)))
    assert fake.paths() == ["/GetPTForDownload", "/Download"]


def test_a_receipt_of_another_ptin_is_not_found(monkeypatch):
    fake = portal(monkeypatch, pages={"/GetPTForDownload": receipt_page(ptin="", qr=False)})
    _raises(NOT_FOUND, client.fetch_receipt_pdf, PTIN, "043700", "11130000000001")
    assert fake.paths() == ["/GetPTForDownload"]


@pytest.mark.parametrize("pages", [
    {"/GetPTForDownload": "<html>Server Error in '/CDMA_ARBS' Application.</html>"},
    {"/GetPTForDownload": receipt_page(qr=False)},
    {"/Download": b"<html>error</html>"},
])
def test_broken_receipt_pages_are_portal_trouble(monkeypatch, pages):
    portal(monkeypatch, pages=pages)
    _raises(PORTAL_DOWN, client.fetch_receipt_pdf, PTIN, "043700", "11130000000001")


@pytest.mark.parametrize("ptin, receipt_no, slno", [
    ("111399900", "043700", "1"), (PTIN, "", "1"), (PTIN, "04 37", "1"), (PTIN, "043700'", "1"),
    (PTIN, "043700", ""), (PTIN, "043700", "12a"), (PTIN, "x" * 41, "1"),
])
def test_bad_receipts_never_reach_the_portal(monkeypatch, ptin, receipt_no, slno):
    fake = portal(monkeypatch)
    _raises(BAD_INPUT, client.fetch_receipt_pdf, ptin, receipt_no, slno)
    assert fake.calls == []


@pytest.mark.parametrize("message, status", [(NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502), (PORTAL_TIMEOUT, 502)])
def test_routes_map_errors_to_friendly_messages(monkeypatch, message, status):
    def fail(*_a, **_k):
        raise PortalError(message)
    for name in ("fetch_property", "find_properties", "fetch_receipt_pdf", "fetch_property_pdf"):
        monkeypatch.setattr(client, name, fail)
    app = _app()
    # the PDFs load into the page's preview, so their errors are JSON like the rest
    for r in (app.post("/api/cdma-tax/property", json={"ptin": PTIN}),
              app.post("/api/cdma-tax/find", json={"town_id": "1113", "owner_name": "SAMPLE"}),
              app.get("/api/cdma-tax/receipt", params={"ptin": PTIN, "receipt_no": "043700", "slno": "1"}),
              app.get(f"/api/cdma-tax/pdf/{PTIN}")):
        assert r.status_code == status and r.json() == {"detail": message}


def test_routes_serve_lookup_towns_and_the_pdf_inline(monkeypatch):
    portal(monkeypatch)
    app = _app()
    assert app.post("/api/cdma-tax/property", json={"ptin": PTIN}).json()["dues"]["total"] == 1140
    assert len(app.get("/api/cdma-tax/towns").json()) == 32
    r = app.get("/api/cdma-tax/receipt", params={"ptin": PTIN, "receipt_no": "043700", "slno": "11130000000001"})
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == f'inline; filename="CDMA-tax-receipt-{PTIN}-043700.pdf"'
    r = app.get(f"/api/cdma-tax/pdf/{PTIN}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-") and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == f'inline; filename="CDMA-property-tax-{PTIN}.pdf"'


def pdf_pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type /Page[^s]", pdf))


def test_details_pdf_shows_what_the_page_shows(monkeypatch):
    fake = portal(monkeypatch)
    monkeypatch.setattr(rl_config, "pageCompression", 0)  # page text readable in the bytes
    client.fetch_property(PTIN)
    pdf, name = client.fetch_property_pdf(PTIN)
    assert pdf.startswith(b"%PDF-") and name == f"CDMA-property-tax-{PTIN}.pdf" and pdf_pages(pdf) == 1
    assert f"(Property tax details: PTIN {PTIN})".encode() in pdf  # the document title
    for text in (f"Property Tax Details: PTIN {PTIN}", "Siddipet Municipality, Telangana", "SAMPLE OWNER", "9-9-99", "Sample Nagar",
                 "Residential", "Tax due as on 22/10/2026", "Rs. 500", "Rs. 40", "Rs. 600", "Rs. 1,140", "2 tax receipts",
                 "190924000000000000001", "Rs. 1,200", "2023-2024-1 to 2024-2025-2", "043700", "For reference only"):
        assert text.encode() in pdf, text
    assert b"PENALTY" not in pdf and b"ADJUSTMENT" not in pdf  # shown only when charged, as on the page
    assert pdf.count(b"(Only For Information)") == 1  # the watermark
    assert fake.paths() == ["/GetReciptDetails", "/GetPTDetails_PV"]  # the PDF reused the look-up


def test_details_pdf_charges_and_empty_parts(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    data = {"ptin": PTIN, "property": None, "dues": None, "receipts": []}
    pdf = client._property_pdf(data, datetime(2026, 10, 22, 14, 5, tzinfo=client.IST))
    assert b"(Telangana)" in pdf and b"No tax receipts on the portal for this PTIN yet" in pdf and b"OWNER" not in pdf
    assert b"Made with TruDocs on 22 Oct 2026, 14:05 IST." in pdf
    dues = {"as_on": "22/10/2026", "arrear_tax": 0, "arrear_interest": 0, "current_tax": 123456, "current_interest": 0,
            "cheque_bounce_penalty": 250, "deviation_penalty": 0, "adjustment": 0, "total": 123706}
    pdf = client._property_pdf({**data, "dues": dues}, datetime.now(client.IST))
    assert b"CHEQUE BOUNCE PENALTY" in pdf and b"DEVIATION PENALTY" not in pdf and b"Rs. 1,23,706" in pdf


def test_a_long_receipt_history_continues_on_the_next_page(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    receipts = [{"date": "01/04/2020", "paid_from": "2020-2021-1", "paid_to": "2020-2021-2", "receipt_no": f"MIDPTOP{n:020d}",
                 "mode": "BD-UPI", "amount": 1132, "slno": "1"} for n in range(60)]
    pdf = client._property_pdf({"ptin": PTIN, "property": None, "dues": None, "receipts": receipts}, datetime.now(client.IST))
    assert pdf_pages(pdf) >= 2 and b"Page 2" in pdf and pdf.count(b"RECEIPT NO.") == pdf_pages(pdf)  # headings repeat
    assert pdf.count(b"(Only For Information)") == pdf_pages(pdf)  # watermarked on every page
    assert f"MIDPTOP{59:020d}".encode() in pdf


@pytest.mark.parametrize("amount, text", [(0, "Rs. 0"), (999, "Rs. 999"), (1534, "Rs. 1,534"), (123456, "Rs. 1,23,456"),
                                          (12345678, "Rs. 1,23,45,678"), (1534.5, "Rs. 1,534.5"), (-250, "-Rs. 250"), (None, "-")])
def test_rupees_use_indian_grouping_like_the_page(amount, text):
    assert client._rupees(amount) == text


def test_details_pdf_refuses_bad_ptins_before_the_portal(monkeypatch):
    fake = portal(monkeypatch)
    r = _app().get("/api/cdma-tax/pdf/11139")
    assert r.status_code == 400 and r.json() == {"detail": BAD_INPUT} and fake.calls == []
