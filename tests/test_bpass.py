"""TG-bPASS Building Permission tests. Synthetic search replies shaped like the portal's
(made-up applicants, file numbers and IDs, no real records); the portal itself is faked."""
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.routers import bpass as bpass_router
from backend.scrapers.bpass import client

FILE = "999901/TEST/0001/2025"
PDF = b"%PDF-1.4 synthetic letter"


def link(kind):
    return f"https://{client.DOCS_HOST}/{kind}/SC/999901_TEST_0001_2025.pdf?X-Amz-Expires=3600&X-Amz-Signature=abc"


def row(n=1, file_no=FILE, status="ACCEPTED", certificates=None):
    return {"id": 9000 + n, "application_id": file_no, "applicant_name": f"SAMPLE OWNER {n}", "application_type": "SC",
            "approval_for": "BUILDING", "status": status, "applied_on": "2025-08-01T10:00:00.000+05:30",
            "created_at": "2025-07-30T10:00:00.000+05:30", "completed_date": "2025-08-07T10:00:00.000+05:30",
            "ulb": "Sampletown", "district_name": "Sangareddy", "survey_no": "999/9/Z", "plot_no": "99", "locality": "Sample Colony",
            "certificates": certificates if certificates is not None else
            {"Acknowledgement": link("Acknowledgement"), "WorkCommencement": link("WorkCommencement"), "Revocation": None}}


def reply(rows, total=None):
    return {"success": True, "message": "", "data": {"applications": rows, "pagination_info": {"total_count": len(rows) if total is None else total}}}


class Resp:
    def __init__(self, payload=None, content=b"", status=200, not_json=False):
        self.payload, self.content, self.status_code, self.not_json = payload, content, status, not_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("portal error", request=httpx.Request("GET", "https://x"), response=httpx.Response(self.status_code))

    def json(self):
        if self.not_json:
            raise ValueError("not JSON")
        return self.payload


class FakePortal:
    """Stands in for httpx.Client: answers the search from `searches` and links from `files`."""

    def __init__(self, searches=None, files=None, delay=0.0):
        self.searches = searches or (lambda body: Resp(reply([row()])))
        self.files = files if files is not None else {}
        self.delay, self.calls = delay, []

    def __call__(self, timeout=60.0):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, method, path, json=None, **kw):
        self.calls.append(("search", json))
        time.sleep(self.delay)
        result = self.searches(json)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, **kw):
        self.calls.append(("file", url))
        time.sleep(self.delay)
        return Resp(content=self.files.get(url, PDF))

    def searched(self):
        return [b for kind, b in self.calls if kind == "search"]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for fn in (client._application, client._links, client._document):
        fn.cache_clear()
    monkeypatch.setattr(client._throttle, "min_interval_seconds", 0)
    yield
    for fn in (client._application, client._links, client._document):
        fn.cache_clear()


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
    app.include_router(bpass_router.router)
    return TestClient(app)


def test_file_number_lookup_gives_status_place_and_letters(monkeypatch):
    fake = portal(monkeypatch)
    r = client.fetch_application(" 999901/test/0001/2025 ")
    assert r["file_no"] == FILE and r["found"] and "applicant" not in r
    assert (r["status"], r["approval_for"], r["type"]) == ("Approved", "Building", "Instant approval")
    assert (r["town"], r["district"], r["survey_no"], r["plot_no"]) == ("Sampletown", "Sangareddy", "999/9/Z", "99")
    assert (r["applied_on"], r["decided_on"]) == ("2025-08-01", "2025-08-07")
    # the approval letter first, then the permit order; empty slots are left out
    assert [d["kind"] for d in r["documents"]] == ["WorkCommencement", "Acknowledgement"]
    body = fake.searched()[0]
    assert body["application_identifier"] == FILE
    assert set(body) == set(client._EMPTY)  # never an unknown key: that would mean no filter at all


def test_only_the_public_search_is_used(monkeypatch):
    fake = portal(monkeypatch)
    client.fetch_application(FILE)
    assert [kind for kind, _ in fake.calls] == ["search"]  # never the portal's detail page


def test_a_pending_application_has_no_decision_date(monkeypatch):
    portal(monkeypatch, searches=lambda b: Resp(reply([row(status="SUBMITTED")])))
    r = client.fetch_application(FILE)
    assert r["status"] == "Submitted" and r["decided_on"] == ""


def test_unknown_file_number_and_a_near_miss_are_not_found(monkeypatch):
    portal(monkeypatch, searches=lambda b: Resp(reply([])))
    _raises(NOT_FOUND, client.fetch_application, FILE)
    client._application.cache_clear()
    portal(monkeypatch, searches=lambda b: Resp(reply([row(file_no=FILE + "/REV")])))
    _raises(NOT_FOUND, client.fetch_application, FILE)  # only the exact file number counts


@pytest.mark.parametrize("bad", ["", "12", "9999 01/TEST", "999901/TEST/0001/2025;", "x" * 41, "{\"a\":1}"])
def test_bad_file_numbers_never_reach_the_portal(monkeypatch, bad):
    fake = portal(monkeypatch)
    _raises(BAD_INPUT, client.fetch_application, bad)
    assert fake.calls == []


@pytest.mark.parametrize("answer, message", [
    (Resp(not_json=True), PORTAL_DOWN),                                  # an HTML error page
    (Resp({"success": False, "message": "error"}), PORTAL_DOWN),
    (Resp({"success": True, "data": {"applications": "x"}}), PORTAL_DOWN),
    (Resp(status=502), PORTAL_DOWN),
    (httpx.ReadTimeout("slow"), PORTAL_TIMEOUT),
    (httpx.ConnectError("down"), PORTAL_DOWN),
])
def test_portal_trouble_is_friendly(monkeypatch, answer, message):
    portal(monkeypatch, searches=lambda b: answer)
    _raises(message, client.fetch_application, FILE)


def test_identical_lookups_share_one_search_and_repeats_are_cached(monkeypatch):
    fake = portal(monkeypatch, delay=0.2)
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda _: client.fetch_application(FILE), range(5)))
    assert all(r == results[0] for r in results)
    client.fetch_application(FILE)
    assert len(fake.searched()) == 1


def test_only_the_portals_own_pdf_links_are_kept():
    docs = client._documents({
        "WorkCommencement": link("WorkCommencement"),
        "Acknowledgement": "https://evil.example.com/Acknowledgement/x.pdf",
        "FeeIntimation": f"https://{client.DOCS_HOST}/FeeIntimation/x.exe",
        "Unknown": link("Unknown"),
        "Revocation": None,
    })
    assert list(docs) == ["WorkCommencement"]
    assert client._documents("not a dict") == {}


def test_a_letter_is_downloaded_with_a_fresh_link_and_cached(monkeypatch):
    fake = portal(monkeypatch)
    pdf, name = client.fetch_document(FILE, "WorkCommencement")
    assert pdf == PDF and name == "TG-bPASS-WorkCommencement-999901-TEST-0001-2025.pdf"
    assert ("file", link("WorkCommencement")) in fake.calls
    searches_before = len(fake.searched())
    client.fetch_document(FILE, "WorkCommencement")
    assert len(fake.searched()) == searches_before and sum(1 for k, _ in fake.calls if k == "file") == 1


def test_letters_the_portal_doesnt_hold_and_bad_kinds(monkeypatch):
    fake = portal(monkeypatch)
    _raises(NOT_FOUND, client.fetch_document, FILE, "Revocation")  # an empty slot
    calls = len(fake.calls)
    _raises(BAD_INPUT, client.fetch_document, FILE, "../../etc/passwd")
    assert len(fake.calls) == calls


def test_a_file_that_isnt_a_pdf_is_portal_trouble(monkeypatch):
    portal(monkeypatch, files={link("WorkCommencement"): b"<html>AccessDenied</html>"})
    _raises(PORTAL_DOWN, client.fetch_document, FILE, "WorkCommencement")


@pytest.mark.parametrize("message, status", [(NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502), (PORTAL_TIMEOUT, 502)])
def test_routes_map_errors_to_friendly_messages(monkeypatch, message, status):
    def fail(*_a, **_k):
        raise PortalError(message)
    for name in ("fetch_application", "fetch_document"):
        monkeypatch.setattr(client, name, fail)
    app = _app()
    for r in (app.post("/api/bpass/application", json={"file_no": FILE}),
              app.get("/api/bpass/document", params={"file_no": FILE, "kind": "WorkCommencement"})):
        assert r.status_code == status and r.json() == {"detail": message}


def test_routes_serve_the_lookup_and_the_pdf_inline(monkeypatch):
    portal(monkeypatch)
    app = _app()
    assert app.post("/api/bpass/application", json={"file_no": FILE}).json()["status"] == "Approved"
    r = app.get("/api/bpass/document", params={"file_no": FILE, "kind": "WorkCommencement"})
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="TG-bPASS-WorkCommencement-999901-TEST-0001-2025.pdf"'
