"""22-A prohibited-lands scraper checks against trimmed copies of real portal
responses (captured 2026-10-15). No network: the portal is never called.

Run from the repo root:  python -m pytest tests
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PortalError
from backend.routers import prohibited_lands as pl_router
from backend.scrapers.prohibited_lands import client


def _column(heading, kind, sro=""):
    args = lambda ft: f"'15_1', '07', '1516004', '{sro}', '{kind}', '{ft}'"
    return f"""
<div class="col-md-6 col-sm-6 pdf_link">
 <h4 style="margin-top: 0;">{heading}</h4>
 <input type="hidden" name="dist_code" id="dist_code_agri" value="15_1"/>
 <button type="button" ng-click="getpdf1({args(1)})"><img src="/resources/img/pdf_1.png"> 22 A (1) (a)</button>
 <button type="button" ng-click="getpdf1({args(2)})" ><img src="/resources/img/pdf_1.png"> 22 A (1) (b)</button>
 <button type="button" ng-click="getpdf1('', '', '', '', '', '')" ><img src="/resources/img/pdf_1.png"> 22 A (1) (c)- Waqf</button>
 <button type="button" ng-click="getpdf1('', '', '', '', '', '')"><img src="/resources/img/pdf_1.png"> 22 A (1) (c)- Endowment</button>
 <button type="button" ng-click="getpdf1({args(5)})"><img src="/resources/img/pdf_1.png"> 22 A (1) (d)</button>
 <button type="button" ng-click="getpdf1({args(6)})"><img src="/resources/img/pdf_1.png"> 22 A (1) (e)</button>
 <form id="form" action="prohibitedPropertyDetails_New.htm" method="post">
  <input type="hidden" name="prohib_type" id="prohib_type" value="{kind}"/>
  <button type="submit"><img src="/resources/img/pdf_1.png"> Court cases & Others</button>
 </form>
</div>"""


PANEL_HEAD = '<h3 style="background: #428ac7;">SECTION 22A(1) : PROHIBITION LIST</h3>'
PANEL_HTML = PANEL_HEAD + _column("Agriculture", "AGRI") + _column("Non-Agriculture", "NONAGRI")
HYD_PANEL_HTML = PANEL_HEAD + _column("Non-Agriculture", "NONAGRI", sro="1604")

# Two header rows and two data rows as the portal sends them, including the
# commented-out columns (combined TS no, remarks, authority).
SURVEY_HTML = """
<table width="100%" class="table table-bordered table-responsive" id="report">
<thead>
<tr> <th rowspan="2">Sro Name<br/>[Sro Code]</th> <th rowspan="2">Ward - Block No</th> <th rowspan="2">Door <br/>No.</th>
 <th rowspan="2">Survey <br/>No.</th> <th rowspan="2">Sub <br/>Sy No.</th> <th rowspan="2">Rev <br/>Sy No.</th> <th rowspan="2">Rev Sub <br/>Sy No.</th>
 <!--<th rowspan="2">Combined Town <br/>Survey No</th>--> <th rowspan="2">Plot No.</th> <th rowspan="2">Extent <br/>(Unit)</th>
 <th >Volume <br/>No.</th> <th rowspan="2">Reason</th> <th >Letter/Memo/<br/>Order/Notification<br/> No.</th>
 <!--<th rowspan="2">Remarks</th>--> <!--<th rowspan="2" >Authority</th>--> </tr>
<tr> <th >Page No.</th> <th >Letter/Memo/<br/>Order/Notification<br/> Date</th> </tr>
</thead>
<tr> <td >GANDIPET<br/>[1525]</td> <td >0 - 1</td> <td >1-107</td> <td >-</td> <td >-</td> <td ></td> <td ></td>
 <!--<td >0-1-</td>--> <td >-</td> <td >100.0(Y)</td> <td >34 <hr/>190</td> <td >Ceiling Surplus Land</td>
 <td > <a href="#" onclick="getFileView('250801162423216','HU')" > IA NO.505/2023 I NOS NO.686/2023 </a> <hr/> 01-08-2025 </td>
 <!--<td >1-107 IN GRAMAKANTAM</td>--> <!--<td >--> <!--V ADDL DIST JUDGE--> <!--</td>--> </tr>
<tr> <td >GANDIPET<br/>[1525]</td> <td >- - -</td> <td >-</td> <td >166</td> <td >3</td> <td >166</td> <td >3</td>
 <td >-</td> <td >15.0(A)</td> <td >36 <hr/>195</td> <td >Ceiling Surplus Land</td>
 <td > ARB OP NO 142 OF 2023 <hr/> 25-09-2023 </td> </tr>
</table>
"""

ERROR_HTML = "<html><body>Error Page Error Msg &nbsp; No Data Found We are unable to process your request.</body></html>"


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as info:
        fn(*args, **kwargs)
    assert info.value.user_message == user_message


def test_categories_show_what_is_online():
    cats = client._parse_categories(PANEL_HTML)["categories"]
    assert set(cats) == {"AGRI", "NONAGRI"}
    assert [(c["label"], c["formtype"], c["available"]) for c in cats["AGRI"]] == [
        ("22A(1)(a)", "1", True),
        ("22A(1)(b)", "2", True),
        ("22A(1)(c) - Waqf", "", False),
        ("22A(1)(c) - Endowment", "", False),
        ("22A(1)(d)", "5", True),
        ("22A(1)(e)", "6", True),
    ]
    assert [c["available"] for c in cats["NONAGRI"]] == [True, True, False, False, True, True]


def test_hyderabad_has_non_agriculture_only():
    cats = client._parse_categories(HYD_PANEL_HTML)["categories"]
    assert list(cats) == ["NONAGRI"]


def test_unknown_page_is_portal_error():
    _raises(PORTAL_DOWN, client._parse_categories, "<html><body>Service Unavailable</body></html>")
    _raises(PORTAL_DOWN, client._parse_survey_list, "<html><body>Service Unavailable</body></html>")


def test_survey_rows_hold_only_visible_columns():
    rows = client._parse_survey_list(SURVEY_HTML)
    assert rows == [
        {
            "sro": "GANDIPET [1525]", "ward_block": "0 - 1", "door_no": "1-107", "survey_no": "-",
            "sub_survey_no": "-", "rev_survey_no": "", "rev_sub_survey_no": "", "plot_no": "-",
            "extent": "100.0(Y)", "volume_page": "34 / 190", "reason": "Ceiling Surplus Land",
            "order_no": "IA NO.505/2023 I NOS NO.686/2023", "order_date": "01-08-2025",
            "order_id": "250801162423216", "order_flag": "HU",
        },
        {
            "sro": "GANDIPET [1525]", "ward_block": "- - -", "door_no": "-", "survey_no": "166",
            "sub_survey_no": "3", "rev_survey_no": "166", "rev_sub_survey_no": "3", "plot_no": "-",
            "extent": "15.0(A)", "volume_page": "36 / 195", "reason": "Ceiling Surplus Land",
            "order_no": "ARB OP NO 142 OF 2023", "order_date": "25-09-2023",
            "order_id": "", "order_flag": "",
        },
    ]
    assert "GRAMAKANTAM" not in str(rows)  # commented-out remarks never leak through


def test_no_data_page_is_an_empty_list():
    assert client._parse_survey_list(ERROR_HTML) == []


def test_pdf_checks():
    assert client._published('{"message":"success","pdf":"valid"}') is True
    assert client._published('{"message":"fail"}') is False
    assert client._published("<html>not json</html>") is False
    assert client._require_pdf(b"%PDF-1.4 ...") == b"%PDF-1.4 ..."
    _raises(client.DOC_UNAVAILABLE, client._require_pdf, b"<html>Error Msg</html>")


def test_pdfs_are_named_after_the_place_and_list(monkeypatch):
    def portal(_client, method, path, **kwargs):
        reply = '{"message":"success","pdf":"valid"}' if path == "/checkPDFFile.htm" else ""
        return type("Reply", (), {"text": reply, "content": b"%PDF-1.4 list"})()

    monkeypatch.setattr(client, "_request", portal)
    name = lambda **kw: client.fetch_category_pdf(**{"sro_code": "", "kind": "AGRI", "formtype": "1", **kw})[1]
    assert name(district_id="15_1", mandal_id="07", village_id="1516004") == \
        "Prohibited Lands (Section 22A) - KOKAPET - GANDIPET mandal - 22A(1)(a) Agriculture.pdf"
    hyderabad = dict(district_id="16_1", mandal_id="00", village_id="1600001", sro_code="1608", kind="NONAGRI", formtype="5")
    monkeypatch.setattr(client, "fetch_hyderabad_sros", lambda division: [{"value": "1608", "label": "CHARMINAR"}])
    assert name(**hyderabad) == "Prohibited Lands (Section 22A) - HYDERABAD DIVISION - SRO CHARMINAR - 22A(1)(d) Non-Agriculture.pdf"

    def offices_down(division):
        raise PortalError(PORTAL_DOWN, "SRO list down")
    monkeypatch.setattr(client, "fetch_hyderabad_sros", offices_down)  # the office's number when its name can't be had
    assert name(**hyderabad) == "Prohibited Lands (Section 22A) - HYDERABAD DIVISION - SRO 1608 - 22A(1)(d) Non-Agriculture.pdf"
    assert client.fetch_order_pdf("241210114637301", "HU", " B2/15258/2021 ")[1] == "Prohibited Lands (Section 22A) - Order B2-15258-2021.pdf"
    assert client.fetch_order_pdf("241210114637301", "HU", "<b>x</b>")[1] == "Prohibited Lands (Section 22A) - Order ID 241210114637301.pdf"


def test_inputs_are_checked_before_the_portal():
    _raises(BAD_INPUT, client.fetch_categories, district_id="15", mandal_id="07", village_id="1516004")
    _raises(BAD_INPUT, client.fetch_categories, district_id="16_1", mandal_id="00", village_id="1600001")  # no SRO
    _raises(BAD_INPUT, client.fetch_survey_list, district_id="15_1", mandal_id="07", village_id="1516004", kind="BOTH")
    _raises(BAD_INPUT, client.fetch_category_pdf, district_id="15_1", mandal_id="07", village_id="1516004",
            sro_code="", kind="AGRI", formtype="1;")
    _raises(BAD_INPUT, client.fetch_order_pdf, "../etc", "HU")
    _raises(BAD_INPUT, client.fetch_order_pdf, "250801162423216", "hu")
    _raises(BAD_INPUT, client.fetch_hyderabad_sros, "1600001'")
    # Telugu and full-width digits are not 0-9
    _raises(BAD_INPUT, client.fetch_categories, district_id="15_1", mandal_id="౦౭", village_id="1516004")
    _raises(BAD_INPUT, client.fetch_categories, district_id="15_1", mandal_id="07", village_id="１５１６００４")
    _raises(BAD_INPUT, client.fetch_order_pdf, "౨౫౦౮౦౧౧౬౨౪౨౩", "HU")


def _app():
    app = FastAPI()
    app.include_router(pl_router.router)
    return TestClient(app)


@pytest.mark.parametrize("message, status", [
    (client.NOT_PUBLISHED, 404), (NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502), (client.DOC_UNAVAILABLE, 502),
])
def test_json_routes_map_errors(monkeypatch, message, status):
    def fail(**_):
        raise PortalError(message)

    monkeypatch.setattr(client, "fetch_categories", fail)
    resp = _app().post("/api/prohibited-lands/categories", json={"district_id": "15_1", "mandal_id": "07", "village_id": "1516004"})
    assert resp.status_code == status
    assert resp.json()["detail"] == message


def test_pdf_routes_stream_the_pdf_or_a_json_error(monkeypatch):
    # The official PDFs load into the page's preview, which shows the error's message.
    query = "district_id=15_1&mandal_id=07&village_id=1516004&kind=AGRI&formtype=1"
    monkeypatch.setattr(client, "fetch_category_pdf", lambda **_: (b"%PDF-1.4 x", "22A-AGRI-1-1516004.pdf"))
    monkeypatch.setattr(client, "fetch_order_pdf", lambda *_: (b"%PDF-1.4 y", "22A-order-1234567.pdf"))
    ok = _app().get(f"/api/prohibited-lands/pdf?{query}")
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/pdf"
    assert ok.headers["content-disposition"] == 'inline; filename="22A-AGRI-1-1516004.pdf"'
    ok = _app().get("/api/prohibited-lands/order?order_id=1234567&flag=G")
    assert ok.status_code == 200 and ok.content == b"%PDF-1.4 y"
    assert ok.headers["content-disposition"] == 'inline; filename="22A-order-1234567.pdf"'

    def fail(*_a, **_k):
        raise PortalError(client.NOT_PUBLISHED)

    monkeypatch.setattr(client, "fetch_category_pdf", fail)
    monkeypatch.setattr(client, "fetch_order_pdf", fail)
    for bad in (_app().get(f"/api/prohibited-lands/pdf?{query}"), _app().get("/api/prohibited-lands/order?order_id=1234567&flag=G")):
        assert bad.status_code == 404 and bad.json() == {"detail": client.NOT_PUBLISHED}


def test_identical_searches_at_once_hit_the_portal_once(monkeypatch):
    calls = []

    def slow_portal(_client, method, path, **kwargs):
        calls.append(path)
        time.sleep(0.2)
        text = PANEL_HTML if path == "/prohibitionPublicList.htm" else SURVEY_HTML
        return type("Reply", (), {"text": text})()

    monkeypatch.setattr(client, "_request", slow_portal)
    client._categories.cache_clear()
    client._survey_list.cache_clear()
    loc = dict(district_id="15_1", mandal_id="07", village_id="1516004")
    with ThreadPoolExecutor(8) as pool:
        cats = list(pool.map(lambda _: client.fetch_categories(**loc), range(8)))
        lists = list(pool.map(lambda _: client.fetch_survey_list(**loc, kind="AGRI"), range(8)))
    client._categories.cache_clear()
    client._survey_list.cache_clear()
    assert calls == ["/prohibitionPublicList.htm", "/prohibitedPropertyDetails_New.htm"]
    assert all(c == cats[0] for c in cats)
    assert all(lst == lists[0] and lst["count"] == 2 for lst in lists)
