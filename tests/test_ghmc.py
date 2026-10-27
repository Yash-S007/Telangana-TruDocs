"""GHMC Mutation Status and Property Tax as our PDFs. Made-up records; no network."""
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab import rl_config

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PortalError
from backend.core.rate_limit import RateLimiter
from backend.routers import ghmc as ghmc_router
from backend.scrapers.ghmc import mutation_client, property_tax_client
from backend.scrapers.ghmc.record_pdf import field_label

MUTATION = {"source": "ghmc_mutation_status", "assessment_number": "1010199999", "found": True,
            "raw_fields": {"lblAssessmentNum": "1010199999", "lblOwnerName": "SAMPLE OWNER", "lblMutationStatus": "Approved"}}
TAX = {"source": "ghmc_property_tax", "query": "1010199999", "found": True,
       "raw_fields": {"grd_SearchResult_lblptinno_0": "1010199999", "grd_SearchResult_lblOwner_0": "SAMPLE OWNER",
                      "grd_SearchResult_lblDoor_0": "9-9-99", "grd_SearchResult_lbl_arrear_amount_0": "1,140"}}


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(ghmc_router.router)
    return TestClient(app)


def _shown_text(content: bytes) -> bytes:
    return b" ".join(re.findall(rb"\(((?:[^()\\]|\\.)*)\) Tj", content))


@pytest.mark.parametrize("key, label", [
    ("lblOwnerName", "Owner Name"), ("grd_SearchResult_lblptinno_0", "PTIN Number"), ("ContentPlaceHolder1_lblDoor", "Door Number"),
    ("lblAssessmentNum", "Assessment Number"), ("lblMutationStatus", "Mutation Status"), ("lbl_arrear_amount_2", "Arrear amount"),
    ("lbl", "lbl"),
])
def test_field_ids_read_as_the_page_showed_them(key, label):
    assert field_label(key) == label


def test_mutation_pdf(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    monkeypatch.setattr(mutation_client, "fetch_mutation_status", lambda number: MUTATION)
    r = _app().post("/api/ghmc/mutation/pdf", json={"assessment_number": " 1010199999 "})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="GHMC-mutation-1010199999.pdf"'
    text = _shown_text(r.content)
    for shown in (b"GHMC Mutation Status", b"Assessment No. 1010199999", b"Owner Name", b"SAMPLE OWNER", b"Mutation Status",
                  b"Approved", b"not an official GHMC document"):
        assert shown in text, shown


def test_property_tax_pdf_names_the_circle(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    monkeypatch.setattr(property_tax_client, "fetch_property_tax", lambda **_: TAX)
    monkeypatch.setattr(property_tax_client, "fetch_circles", lambda: [{"value": "17", "label": "Circle-17 (Khairatabad)"}])
    r = _app().post("/api/ghmc/property-tax/pdf", json={"circle": "17", "ptin": "1010199999"})
    assert r.status_code == 200 and r.headers["content-disposition"] == 'inline; filename="GHMC-property-tax-1010199999.pdf"'
    text = _shown_text(r.content)
    for shown in (b"GHMC Property Tax", b"PTIN 1010199999 \\267 Circle-17 \\(Khairatabad\\) circle", b"PTIN Number",
                  b"Owner Name", b"Door Number", b"9-9-99", b"Arrear amount", b"1,140"):
        assert shown in text, shown


def test_a_page_without_fields_is_no_record(monkeypatch):
    monkeypatch.setattr(mutation_client, "fetch_mutation_status", lambda number: {**MUTATION, "raw_fields": {}, "found": False})
    r = _app().post("/api/ghmc/mutation/pdf", json={"assessment_number": "1010199999"})
    assert r.status_code == 404 and r.json() == {"detail": NOT_FOUND}


@pytest.mark.parametrize("message, status", [(NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502)])
def test_errors_are_json_with_the_right_status(monkeypatch, message, status):
    def fail(*_a, **_k):
        raise PortalError(message)
    monkeypatch.setattr(mutation_client, "fetch_mutation_status", fail)
    monkeypatch.setattr(property_tax_client, "fetch_property_tax", fail)
    mutation, tax = {"assessment_number": "1"}, {"circle": "17", "ptin": "1"}
    for path, body in (("/api/ghmc/mutation", mutation), ("/api/ghmc/mutation/pdf", mutation),
                       ("/api/ghmc/property-tax", tax), ("/api/ghmc/property-tax/pdf", tax)):
        r = _app().post(path, json=body)
        assert r.status_code == status and r.json() == {"detail": message}, path


@pytest.fixture
def no_ghmc(monkeypatch):
    """Any request that gets past our checks fails the test instead of reaching GHMC."""
    def refuse(self, request):
        raise AssertionError(f"reached {request.url.host}")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.mark.parametrize("number", ["abc", "12ab", "౧౨౩", "１２３", "12345678901", "😀", "1 2", "<b>1</b>"])
def test_numbers_are_digits_only_and_never_reach_ghmc(no_ghmc, number):
    r = _app().post("/api/ghmc/mutation", json={"assessment_number": number})
    assert r.status_code == 400 and r.json() == {"detail": mutation_client.DIGITS_ONLY}
    r = _app().post("/api/ghmc/property-tax/pdf", json={"circle": "17", "ptin": number})
    assert r.status_code == 400 and r.json() == {"detail": property_tax_client.DIGITS_ONLY}


@pytest.mark.parametrize("body", [{"circle": "Circle 17", "ptin": "1010199999"}, {"circle": "17", "owner_name": "రాము"},
                                  {"circle": "17", "door_no": "1-2-3; DROP"}])
def test_circle_owner_and_door_are_checked_too(no_ghmc, body):
    r = _app().post("/api/ghmc/property-tax", json=body)
    assert r.status_code == 400 and r.json() == {"detail": BAD_INPUT}


def test_circle_list_uses_our_copy_while_ghmc_is_down(monkeypatch):
    monkeypatch.setattr(property_tax_client, "_throttle", RateLimiter(0))
    property_tax_client._fetch_circles_cached.cache_clear()

    def down(self, request):
        raise httpx.ConnectError("down", request=request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", down)
    r = _app().get("/api/ghmc/circles")
    assert r.status_code == 200 and len(r.json()) == 60 and r.json()[0] == {"value": "1070", "label": "1-Keesara"}
    # a GHMC page without the list (maintenance) isn't remembered as an empty list
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda self, request: httpx.Response(200, html="<html>Under maintenance</html>", request=request))
    assert len(property_tax_client.fetch_circles()) == 60
    assert property_tax_client._fetch_circles_cached.cache_info().currsize == 0
    page = '<select name="ctl00$ContentPlaceHolder1$ddlcircle"><option value="">Select</option><option value="9">9-Sample</option></select>'
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: httpx.Response(200, html=page, request=request))
    assert property_tax_client.fetch_circles() == [{"value": "9", "label": "9-Sample"}]  # the live list when GHMC answers
    property_tax_client._fetch_circles_cached.cache_clear()
