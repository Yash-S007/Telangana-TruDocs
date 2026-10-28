"""Market value scraper checks against trimmed copies of real portal responses
(captured 2026-10-15). No network: the portal is never called.

Run from the repo root:  python -m pytest tests
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab import rl_config

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PortalError
from backend.routers import market_value as mv_router
from backend.scrapers.market_value import client

# Header + two data rows as the portal sends them, including the columns it
# comments out (apartment rate, classification) and the "Get" door-no button.
RATES_HTML = """
<table width="100%" class="table table-bordered table-responsive">
<tr>
  <th class="formhd1">S.No.</th><th class="formhd1">Ward-Block</th><th class="formhd1">Locality</th>
  <th class="formhd1">Land Value<br/>(Rs. per Sq.Yard)</th>
  <!--<th class="formhd1">Apartment value<br/> (Rs. per Sq.Ft)</th>-->
  <!--<th class="formhd1">Classification</th>-->
  <th class="formhd1">Effective Date<br>(dd/mm/yyyy)</th><th class="formhd1">Door No. Wise<br>Details - Rates</th>
</tr>
<tr>
  <td class="formbg2"><b>1.</td>
  <td class="formbg2"><b>0</b>
      -
      <b>4</b></td>
  <td class="formbg2">KOKAPET CHANDRA REDDY CIRCLE TO ORR SERVICE R</td>
  <td class="formbg2">        47,600</td>
  <!--<td class="formbg2">         6,600</td>-->
  <!--<td class="formbg2">02(Commercial)</td>-->
  <td class="formbg2">05/06/2026</td>
  <td class="formbg2">
    <input type="button" name="button" value="Get" class="btn btn-custom" onclick="getDetails('0', '4', 'KOKAPET CHANDRA REDDY CIRCLE TO ORR SERVICE R','        47,600')"/>
  </td>
</tr>
<tr>
  <td class="formbg2"><b>2.</td>
  <td class="formbg2"><b>0</b> - <b>4</b></td>
  <td class="formbg2">KOKAPET VILLAGE MAIN ROADS</td>
  <td class="formbg2">        27,000</td>
  <!--<td class="formbg2">         2,700</td>-->
  <!--<td class="formbg2">01(Residential)</td>-->
  <td class="formbg2">05/06/2026</td>
  <td class="formbg2"></td>
</tr>
</table>
"""

ERROR_MSG_HTML = """<!DOCTYPE html><html><head><title>JSP Page</title></head>
<body><center>  <h1>Error Msg</h1></center></body></html>"""


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as info:
        fn(*args, **kwargs)
    assert info.value.user_message == user_message


def test_parses_only_the_columns_the_portal_shows():
    result = client._parse_rates(RATES_HTML)
    assert result["found"] is True
    assert result["rows"] == [
        {
            "ward_block": "0 - 4",
            "locality": "KOKAPET CHANDRA REDDY CIRCLE TO ORR SERVICE R",
            "land_rate_per_sq_yard": "47,600",
            "effective_date": "05/06/2026",
        },
        {
            "ward_block": "0 - 4",
            "locality": "KOKAPET VILLAGE MAIN ROADS",
            "land_rate_per_sq_yard": "27,000",
            "effective_date": "05/06/2026",
        },
    ]


def test_header_only_table_is_not_found():
    header_only = RATES_HTML.split("<tr>\n  <td")[0] + "</table>"
    _raises(client.NO_RATES, client._parse_rates, header_only)


def test_error_msg_page_is_bad_input():
    _raises(BAD_INPUT, client._parse_rates, ERROR_MSG_HTML)


def test_unknown_page_is_portal_error():
    _raises(PORTAL_DOWN, client._parse_rates, "<html><body>Service Unavailable</body></html>")


def test_pairs_are_parsed_like_the_browser():
    text = "1611/AMEERPET-1 & 6-3##1516024/BANDLAGUDA  (JAGIR)##1604/A/B##\n"
    assert client._parse_pairs(text) == [
        {"value": "1611", "label": "AMEERPET-1 & 6-3"},
        {"value": "1516024", "label": "BANDLAGUDA (JAGIR)"},
        {"value": "1604", "label": "A"},
    ]
    assert client._parse_pairs("") == []
    _raises(BAD_INPUT, client._parse_pairs, "Malicious")


def test_inputs_are_checked_before_the_portal():
    # "~" is the separator inside the portal's `codes` parameter.
    _raises(client.LOCALITY_CHARS, client.search_hyderabad_localities, "1600001", "ab~c")
    _raises(client.LOCALITY_CHARS, client.search_hyderabad_localities, "1600001", "ab")
    _raises(client.LOCALITY_CHARS, client.search_hyderabad_localities, "1600001", "అమీర్‌పేట")
    _raises(BAD_INPUT, client.fetch_rates, district_id="15_1", mandal_id="07", mandal="GANDIPET", village_id="x", village="KOKAPET")
    _raises(BAD_INPUT, client.fetch_rates, district_id="16_1", division_id="1600001", locality_id="1611", locality="")
    # Telugu and full-width digits are not 0-9
    _raises(BAD_INPUT, client.fetch_rates, district_id="15_1", mandal_id="౦౭", village_id="1516004")
    _raises(BAD_INPUT, client.fetch_rates, district_id="15_1", mandal_id="07", village_id="１５１６００４")
    _raises(BAD_INPUT, client.search_hyderabad_localities, "౧౬", "Ameerpet")


def test_village_names_sent_to_igrs_come_from_our_list(monkeypatch):
    sent = []
    monkeypatch.setattr(client, "_rates", lambda fields, _bucket: sent.append(dict(fields)) or {"rows": []})
    client.fetch_rates(district_id="15_1", mandal_id="07", mandal="<b>x</b>", village_id="1516004", village="ANYTHING")
    assert (sent[0]["mndlName"], sent[0]["vlgName"], sent[0]["villageCode"]) == ("GANDIPET", "KOKAPET", "1516004")
    # a village code not on our list, or under another mandal, never reaches IGRS
    _raises(BAD_INPUT, client.fetch_rates, district_id="15_1", mandal_id="07", village_id="9999999")
    _raises(BAD_INPUT, client.fetch_rates, district_id="15_1", mandal_id="08", village_id="1516004")
    assert len(sent) == 1


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(mv_router.router)
    return TestClient(app)


@pytest.mark.parametrize("message, status", [(client.NO_RATES, 404), (NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502)])
def test_router_maps_errors_to_status_codes(monkeypatch, message, status):
    def fail(**_):
        raise PortalError(message)

    monkeypatch.setattr(client, "fetch_rates", fail)
    for path in ("/api/market-value/search", "/api/market-value/pdf"):  # the PDF loads into the preview: JSON errors
        resp = _app().post(path, json={"district_id": "15_1"})
        assert resp.status_code == status
        assert resp.json()["detail"] == message


def test_identical_searches_at_once_hit_the_portal_once(monkeypatch):
    calls = []

    def slow_portal(_client, path, data):
        calls.append(path)
        time.sleep(0.2)
        return type("Reply", (), {"text": RATES_HTML})()

    monkeypatch.setattr(client, "_post", slow_portal)
    client._rates.cache_clear()
    args = dict(district_id="15_1", mandal_id="07", mandal="GANDIPET", village_id="1516004", village="KOKAPET")
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: client.fetch_rates(**args), range(8)))
    client._rates.cache_clear()
    assert len(calls) == 1
    assert all(r == results[0] and r["rows"] for r in results)



def test_pdf_shows_the_rates_and_reuses_the_search(monkeypatch):
    calls = []

    def portal(_client, path, data):
        calls.append(path)
        return type("Reply", (), {"text": RATES_HTML})()

    monkeypatch.setattr(client, "_post", portal)
    monkeypatch.setattr(rl_config, "pageCompression", 0)  # page text readable in the bytes
    client._rates.cache_clear()
    village = dict(district_id="15_1", mandal_id="07", mandal="GANDIPET", village_id="1516004", village=" KOKAPET ")
    assert _app().post("/api/market-value/search", json=village).status_code == 200
    resp = _app().post("/api/market-value/pdf", json=village)
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="Land Market Value - KOKAPET - GANDIPET mandal.pdf"'
    for text in ("Market Value Land Rates: KOKAPET", "GANDIPET mandal, Telangana", "2 land rates", "LAND VALUE",
                 "KOKAPET CHANDRA REDDY", "KOKAPET VILLAGE MAIN ROADS", "47,600", "27,000", "05/06/2026", "Only For Information"):
        assert text.encode() in resp.content, text
    assert len(calls) == 1  # the PDF reused the search

    locality = dict(district_id="16_1", division_id="1600001", locality_id="1611", locality="BANJARA HILLS")
    content, name = client.fetch_rates_pdf(**locality)
    client._rates.cache_clear()
    assert name == "Land Market Value - BANJARA HILLS - Hyderabad.pdf" and b"Market Value Land Rates: BANJARA HILLS" in content
    assert b"Hyderabad \\(GHMC\\), Telangana" in content
