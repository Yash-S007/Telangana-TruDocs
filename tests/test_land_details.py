"""Land Details Search (Pattadar) checks — survey search and the new passbook search.
No network: the portal is never called, and the fixtures use synthetic data only
(never a real person's details).

Run from the repo root:  python -m pytest tests
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab import rl_config

from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PORTAL_DOWN, PortalError
from backend.routers import pattadar_passbook as router_mod
from backend.scrapers.pattadar_passbook import client

# The portal returns each field as <strong>Label</strong><br>Value. Synthetic values.
RESULT_HTML = """<!DOCTYPE html><html><body>
<div class="col"><strong>District</strong><br> Rangareddy </div>
<div class="col"><strong>Pattadar / Authorised Person Name</strong><br> TEST OWNER </div>
<div class="col"><strong>Khata Number</strong><br> 337 </div>
<div class="col"><strong>Land Status</strong><br> Not Prohibited </div>
<div class="col"><strong>Total Extent (Ac. Gts)</strong><br> 1.20 </div>
</body></html>"""

NO_RECORD_HTML = "<html><body><h3>No Record Found</h3></body></html>"
ERROR_HTML = "<html><body>Something went wrong... Click Here to go to home page</body></html>"


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as info:
        fn(*args, **kwargs)
    assert info.value.user_message == user_message


def test_parses_the_field_list():
    r = client._parse_result(RESULT_HTML)
    assert r["found"] is True
    assert r["raw_fields"]["Land Status"] == "Not Prohibited"
    assert r["raw_fields"]["Pattadar / Authorised Person Name"] == "TEST OWNER"
    assert "District" in r["raw_fields"]


def test_no_record_and_error_pages():
    _raises(NOT_FOUND, client._parse_result, NO_RECORD_HTML)
    _raises(PORTAL_DOWN, client._parse_result, ERROR_HTML)


def test_passbook_inputs_checked_before_the_portal():
    _raises(BAD_INPUT, client.fetch_pattadar_by_passbook, passbook_no="", aadhaar_last4="1234")
    _raises(BAD_INPUT, client.fetch_pattadar_by_passbook, passbook_no="123", aadhaar_last4="12")      # not 4 digits
    _raises(BAD_INPUT, client.fetch_pattadar_by_passbook, passbook_no="123", aadhaar_last4="12ab")    # not digits
    _raises(BAD_INPUT, client.fetch_pattadar_by_passbook, passbook_no="123", aadhaar_last4="౧౨౩౪")    # Telugu digits
    _raises(BAD_INPUT, client.fetch_pattadar_by_passbook, passbook_no="has space", aadhaar_last4="1234")
    _raises(BAD_INPUT, client.fetch_pattadar_by_passbook, passbook_no="X" * 13, aadhaar_last4="1234")  # too long


def test_passbook_request_uses_ppb_mode_and_hides_aadhaar(monkeypatch):
    captured = {}

    def fake_search(_client, build_request, _max):
        captured["url"], captured["body"] = build_request("ENC_CAPTCHA")
        return {"source": "pattadar_passbook", "sections": [], "raw_fields": {"Land Status": "ok"}, "found": True}

    monkeypatch.setattr(client, "_search_with_captcha", fake_search)
    monkeypatch.setattr(client, "_get", lambda *a, **k: None)
    client.fetch_pattadar_by_passbook(passbook_no="PPB123", aadhaar_last4="1234")
    assert captured["url"]["flagval"] == "ppb"
    assert captured["url"]["ppbType"] == client._PPB_TYPE_AADHAAR
    assert captured["url"]["ppbno"] == "PPB123"
    # the raw Aadhaar digits are encrypted, never sent in the clear
    assert captured["url"]["adhrfour"] != "1234"
    assert "1234" not in captured["body"].values()


def test_passbook_empty_reply_is_no_record(monkeypatch):
    monkeypatch.setattr(client, "_get", lambda *a, **k: None)
    monkeypatch.setattr(client, "_search_with_captcha",
                        lambda *a: {"source": "pattadar_passbook", "sections": [], "raw_fields": {}, "found": False})
    _raises(NOT_FOUND, client.fetch_pattadar_by_passbook, passbook_no="PPB123", aadhaar_last4="1234")


def test_captcha_loop_retries_then_gives_up(monkeypatch):
    # Every attempt returns the portal's generic error page -> CAPTCHA_FAILED after N tries.
    attempts = []

    class Reply:
        def __init__(self, text, content=b"img"):
            self.text, self.content = text, content
        def raise_for_status(self):
            pass

    class FakeClient:
        def post(self, path, *a, **k):
            if "checkcaptcha" in path:
                return Reply("true")
            attempts.append(1)
            return Reply("Something went wrong... go to home page")

    monkeypatch.setattr(client, "_get", lambda c, p: Reply("", b"imgbytes"))
    monkeypatch.setattr(client, "solve_captcha", lambda b: "ABCDE")
    monkeypatch.setattr(client._throttle, "wait", lambda: None)
    _raises(CAPTCHA_FAILED, client._search_with_captcha, FakeClient(), lambda cap: ({}, {}), 3)
    assert len(attempts) == 3


def _app():
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app)


@pytest.mark.parametrize("message, status", [
    (NOT_FOUND, 404), (BAD_INPUT, 400), (CAPTCHA_FAILED, 503), (PORTAL_DOWN, 502),
])
def test_routes_map_errors(monkeypatch, message, status):
    def fail(**_):
        raise PortalError(message)

    monkeypatch.setattr(client, "fetch_pattadar_by_survey", fail)
    monkeypatch.setattr(client, "fetch_pattadar_by_passbook", fail)
    c = _app()
    survey = {"district_id": "5", "mandal_id": "83", "village_id": "507004", "survey_no": "1", "khata_id": "1"}
    passbook = {"passbook_no": "PPB123", "aadhaar_last4": "1234"}
    # the PDFs load into the page's preview, so their errors are JSON like the searches'
    for r in (c.post("/api/pattadar/search", json=survey), c.post("/api/pattadar/search-by-passbook", json=passbook),
              c.post("/api/pattadar/pdf", json=survey), c.post("/api/pattadar/pdf-by-passbook", json=passbook)):
        assert r.status_code == status and r.json()["detail"] == message


def test_identical_searches_at_once_hit_the_portal_once(monkeypatch):
    calls = []

    def slow(_client, _build, _max):
        calls.append(1)
        time.sleep(0.2)
        return {"source": "pattadar_passbook", "sections": [], "raw_fields": {"Land Status": "ok"}, "found": True}

    monkeypatch.setattr(client, "_get", lambda *a, **k: None)
    monkeypatch.setattr(client, "_search_with_captcha", slow)
    args = dict(district_id="5", mandal_id="83", village_id="507004", survey_no="1/2A", khata_id="337")
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: client.fetch_pattadar_by_survey(**args), range(8)))
    assert len(calls) == 1
    assert all(r["found"] and r == results[0] for r in results)


# ---------- security: validation at the trust boundary + encoded params ----------

def _capture_get(monkeypatch):
    seen = []

    class Reply:
        text = '<option value="337">337</option>'

    def fake_get(_client, path, params=None):
        seen.append((path, params))
        return Reply()

    monkeypatch.setattr(client, "_get", fake_get)
    return seen


def test_dropdown_requests_send_encoded_params_not_pasted_urls(monkeypatch):
    seen = _capture_get(monkeypatch)
    client.fetch_survey_options.__wrapped__("507004")
    client.fetch_khata_options.__wrapped__("507004", "1/2అ")
    assert ("/getSurveyCitizen", {"villId": "507004", "flag": "survey"}) in seen
    assert ("/getKhataNoCitizen", {"villId": "507004", "flag": "khatanos", "surveyNo": "1/2అ"}) in seen
    assert not any("?" in path for path, _ in seen)  # nothing pasted into the URL


def test_injected_or_malformed_inputs_are_rejected_before_the_portal(monkeypatch):
    seen = _capture_get(monkeypatch)
    _raises(BAD_INPUT, client.fetch_survey_options.__wrapped__, "507004&flag=khatanos")
    _raises(BAD_INPUT, client.fetch_khata_options.__wrapped__, "507004", "1&flag=x")
    _raises(BAD_INPUT, client.fetch_khata_options.__wrapped__, "abc", "1/2")
    _raises(BAD_INPUT, client.fetch_mandals.__wrapped__, "5#x")
    _raises(BAD_INPUT, client.fetch_villages.__wrapped__, "")
    _raises(BAD_INPUT, client.fetch_survey_options.__wrapped__, "౫౦౭")  # Telugu digits
    survey = dict(district_id="5", mandal_id="83", village_id="507004", survey_no="1/2అ", khata_id="337")
    _raises(BAD_INPUT, client.fetch_pattadar_by_survey, **{**survey, "district_id": "5;"})
    _raises(BAD_INPUT, client.fetch_pattadar_by_survey, **{**survey, "khata_id": ""})
    _raises(BAD_INPUT, client.fetch_pattadar_by_survey, **{**survey, "survey_no": "1/2<script>"})
    assert [p for p, _ in seen if p != client.LANDING_PATH] == []  # the portal was never asked


def test_real_telugu_survey_numbers_are_allowed():
    # Seen live: "/" plus Telugu letters and vowel signs (ు, ూ) — a \w whitelist would reject these.
    for s in ("1/2అ", "12/ు", "45/ూ1", "123"):
        assert client._check_survey(s) == s


@pytest.mark.parametrize("message, status", [(BAD_INPUT, 400), (PORTAL_DOWN, 502)])
def test_dropdown_endpoints_map_errors_instead_of_500(monkeypatch, message, status):
    def fail(*_):
        raise PortalError(message)

    monkeypatch.setattr(client, "fetch_survey_options", fail)
    monkeypatch.setattr(client, "fetch_khata_options", fail)
    c = _app()
    assert c.get("/api/pattadar/survey-options/507004").status_code == status
    assert c.get("/api/pattadar/khata-options/507004?survey_no=1").status_code == status


def _shown_text(content: bytes) -> bytes:
    """What the pages write in Helvetica (Telugu, in Hind Guntur, is glyph numbers)."""
    return b" ".join(re.findall(rb"\(((?:[^()\\]|\\.)*)\) Tj", content))


def test_record_pdf_shows_the_fields_and_where(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    record = client._parse_result(RESULT_HTML.replace("TEST OWNER", "TEST OWNER | టెస్ట్ ఓనర్"))
    monkeypatch.setattr(client, "fetch_pattadar_by_survey", lambda **_: record)
    r = _app().post("/api/pattadar/pdf", json={"district_id": "13", "mandal_id": "261", "village_id": "1301023", "survey_no": " 1/2అ ",
                                               "khata_id": "337"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="Land Details Search - Ankapoor - Survey No. 1-2.pdf"'
    text = _shown_text(r.content)
    for shown in (b"Land Details \\(Bhu Bharati\\)", b"Pattadar / Authorised Person Name", b"Khata Number", b"337",
                  b"Not Prohibited", b"Total Extent \\(Ac. Gts\\)", b"1.20", b"Only For Information"):
        assert shown in text, shown
    assert b"HindGuntur" in r.content  # the survey number and the owner's Telugu name


def test_passbook_pdf_leaves_out_the_aadhaar_digits(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    monkeypatch.setattr(client, "fetch_pattadar_by_passbook", lambda **_: client._parse_result(RESULT_HTML))
    r = _app().post("/api/pattadar/pdf-by-passbook", json={"passbook_no": "T12345678901", "aadhaar_last4": "9071"})
    assert r.status_code == 200 and r.headers["content-disposition"] == 'inline; filename="Land Details Search - Passbook No. T12345678901.pdf"'
    text = _shown_text(r.content)
    assert b"Passbook No. T12345678901" in text and b"TEST OWNER" in text and b"9071" not in text


def test_a_reply_without_fields_is_no_record(monkeypatch):
    monkeypatch.setattr(client, "fetch_pattadar_by_survey", lambda **_: client._parse_result("<html><body></body></html>"))
    r = _app().post("/api/pattadar/pdf", json={"district_id": "5", "mandal_id": "83", "village_id": "507004", "survey_no": "1",
                                               "khata_id": "1"})
    assert r.status_code == 404 and r.json() == {"detail": NOT_FOUND}


EMPTY_LIST_HTML = '<html><head></head><body>\n<option selected value="0">-- Select --</option>\n</body></html>'  # the portal's own "nothing here"
MAINTENANCE_HTML = "<html><body><h1>Site under maintenance</h1></body></html>"


def _reply_with(monkeypatch, html):
    class Reply:
        text = html
    monkeypatch.setattr(client, "_get", lambda c, path, params=None: Reply())


def test_a_page_without_any_list_is_not_remembered_as_empty(monkeypatch):
    _reply_with(monkeypatch, MAINTENANCE_HTML)
    for fn, args in [(client.fetch_districts, ()), (client.fetch_mandals, ("5",)), (client.fetch_villages, ("83",)),
                     (client.fetch_survey_options, ("507004",)), (client.fetch_khata_options, ("507004", "1"))]:
        fn.cache_clear()
        _raises(PORTAL_DOWN, fn, *args)
        assert fn.cache_info().currsize == 0, fn.__name__
    r = TestClient(_app_with_router()).get("/api/pattadar/survey-options/507004")
    assert r.status_code == 502 and r.json() == {"detail": PORTAL_DOWN}


def test_a_real_empty_list_is_still_an_empty_list(monkeypatch):
    _reply_with(monkeypatch, EMPTY_LIST_HTML)
    client.fetch_khata_options.cache_clear()
    assert client.fetch_khata_options("507004", "99999") == []
    client.fetch_khata_options.cache_clear()


def _app_with_router():
    app = FastAPI()
    app.include_router(router_mod.router)
    return app
