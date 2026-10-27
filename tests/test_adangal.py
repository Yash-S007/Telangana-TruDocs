"""Adangal (Pahani) as our PDF. The portal returned no Pahani for any number tried (Oct 2026), so
these use a made-up table in the portal's markup. No network."""
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab import rl_config

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PortalError
from backend.core.rate_limit import RateLimiter
from backend.routers import adangal as adangal_router
from backend.scrapers.adangal import client

PAHANI = ('<table border="1"><tr><th>Survey No</th><th>Extent<br>(Ac.Gts)</th><th>Pattadar</th></tr>'
          '<tr><td><b>999/Z</b></td><td>1.00</td><td>SAMPLE &amp; OWNER</td></tr><tr><td> </td></tr>'
          '<tr><td>999/Y</td><td>0.20</td></tr></table>')
SEARCH = {"district_id": "13", "division_id": "32", "mandal_id": "261", "village_id": "1301023",
          "survey_or_khata_value": " 999/Z ", "option": "surveyNo"}


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(adangal_router.router)
    return TestClient(app)


def test_table_rows_are_the_cells_text():
    assert client._table_rows(PAHANI) == [["Survey No", "Extent (Ac.Gts)", "Pattadar"], ["999/Z", "1.00", "SAMPLE & OWNER"],
                                          ["999/Y", "0.20"]]


def test_pdf_shows_the_pahani_tables(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    monkeypatch.setattr(client, "fetch_adangal", lambda **_: {"found": True, "raw_tables_html": [PAHANI]})
    r = _app().post("/api/adangal/pdf", json=SEARCH)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="Adangal-Ankapoor-survey-999-Z.pdf"'
    text = b" ".join(re.findall(rb"\(((?:[^()\\]|\\.)*)\) Tj", r.content))
    for shown in (b"Adangal \\(Pahani\\)", b"Survey No. 999/Z", b"Ankapoor village, Adilabad \\(Rural\\) mandal, Adilabad district",
                  b"Pattadar", b"SAMPLE & OWNER", b"999/Y", b"0.20", b"not a certified copy"):
        assert shown in text, shown
    assert b"/MediaBox [ 0 0 841.8898 595.2756 ]" in r.content  # landscape A4, for a Pahani's many columns


def test_khata_search_and_unknown_village(monkeypatch):
    monkeypatch.setattr(client, "fetch_adangal", lambda **_: {"found": True, "raw_tables_html": [PAHANI]})
    content, name = client.fetch_adangal_pdf(**{**SEARCH, "village_id": "999999", "option": "khataNo", "survey_or_khata_value": "77"})
    assert name == "Adangal-khata-77.pdf" and content.startswith(b"%PDF-")


@pytest.mark.parametrize("message, status", [(NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502)])
def test_pdf_errors_are_json_like_the_search(monkeypatch, message, status):
    def fail(**_):
        raise PortalError(message)
    monkeypatch.setattr(client, "fetch_adangal", fail)
    for path in ("/api/adangal/search", "/api/adangal/pdf"):
        r = _app().post(path, json=SEARCH)
        assert r.status_code == status and r.json() == {"detail": message}


@pytest.fixture
def no_ccla(monkeypatch):
    """Any request that gets past our checks fails the test instead of reaching the CCLA site."""
    def refuse(self, request):
        raise AssertionError(f"reached {request.url.host}")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.mark.parametrize("value", ["😀", "<b>1</b>", "1'2\"3", "#@!%&*", "9" * 21, "12.5", "1;2", "   "])
def test_odd_survey_numbers_never_reach_ccla(no_ccla, value):
    r = _app().post("/api/adangal/pdf", json={**SEARCH, "survey_or_khata_value": value})
    assert r.status_code == 400 and r.json()["detail"] in (client.NUMBER_CHARS, BAD_INPUT)


@pytest.mark.parametrize("field", ["district_id", "division_id", "mandal_id", "village_id"])
def test_location_codes_are_digits(no_ccla, field):
    r = _app().post("/api/adangal/search", json={**SEARCH, field: "13a"})
    assert r.status_code == 400 and r.json() == {"detail": BAD_INPUT}


@pytest.mark.parametrize("value", ["999/Z", "45/1/అ", "5A", "12-1"])
def test_real_looking_numbers_pass_our_check(monkeypatch, value):
    def down(self, request):
        raise httpx.ConnectError("down", request=request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", down)
    monkeypatch.setattr(client, "_throttle", RateLimiter(0))
    r = _app().post("/api/adangal/pdf", json={**SEARCH, "survey_or_khata_value": value})
    assert r.status_code == 502  # got past our check, then found the (cut-off) portal down


def test_survey_list_is_a_plain_error_not_a_crash(monkeypatch, no_ccla):
    assert _app().get("/api/adangal/survey-options/13a").status_code == 400
    assert _app().get("/api/adangal/survey-options/1301023", params={"option": "x"}).status_code == 400

    def down(self, request):
        raise httpx.ConnectError("down", request=request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", down)
    monkeypatch.setattr(client, "_throttle", RateLimiter(0))
    r = _app().get("/api/adangal/survey-options/1301023")
    assert r.status_code == 502 and r.json() == {"detail": PORTAL_DOWN}
