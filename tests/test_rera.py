"""RERA Certificate tests. Synthetic pages shaped like the portal's (made-up projects and
IDs, no real records); the portal itself is faked."""
import base64
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PORTAL_DOWN, PortalError
from backend.routers import rera as rera_router
from backend.scrapers.rera import client


def token(project_id=111, ext=""):
    raw = f"ProjectID={project_id}&Division=1&UserID=222&RoleID=1&AppID=333&Action=SEARCH&CharacterD=51&ExtAppID={ext}"
    return base64.b64encode(raw.encode()).decode()


HEADERS = ("Sr No.", "Project Name", "Promoter Name", "View Details", "Last Modified Date", "View Certificate",
           "View Extension Certificate", "Spl. Extension (4 Months)", "View on Map", "Directions")


def row(n, project, promoter, extension=False, special=False):
    btn = lambda tok, fn, title: f"""<a id='btnShow_1' class="btn" data-qstr='{tok}' onclick="return {fn}(this);" title="{title}"><i></i></a>"""
    return (f"<tr><td>{n}</td><td>{project}</td><td>{promoter}</td>"
            f"<td><a href='/PrintPreview/PrintPreview?q=abc%2f{n}&amp;x=1'>View</a></td><td>19/05/2025 00:00:00</td>"
            f"<td>{btn(token(100 + n), 'showFile', 'View Certificate')}</td>"
            f"<td>{btn(token(100 + n, '900'), 'showExtensionFile', 'View Extension Certificate') if extension else '<label>NA</label>'}</td>"
            f"<td>{btn(token(100 + n), 'showWarExtensionFile', 'Spl. Extension') if special else '<label>NA</label>'}</td>"
            "<td>NA</td><td>NA</td></tr>")


def results_page(rows, total):
    head = "".join(f"<th>{h}</th>" for h in HEADERS)
    return (f'<form><input name="__RequestVerificationToken" type="hidden" value="tok2" /></form>'
            f"<table><tr>{head}</tr>{''.join(rows)}</table>"
            f'<input type="hidden" id="TotalRecords" name="TotalRecords" value="{total}" />')


SEARCH_PAGE = '<form><input name="__RequestVerificationToken" type="hidden" value="tok1" /></form>'
WRONG_CAPTCHA = SEARCH_PAGE + "<script>swal('Captcha is not valid.');</script>"
NO_RECORDS = SEARCH_PAGE + '<h4><label for="No_Records_Found">No Records Found</label></h4>'
RESULTS = results_page([row(1, "Sample Heights", "SAMPLE BUILDERS", extension=True), row(2, "Test Meadows &amp; Villas", "TEST INFRA", special=True)], 2)
PDF = b"%PDF-1.4 synthetic"


class Reply:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content or text.encode()


class FakePortal:
    def __init__(self, answers=(RESULTS,), viewer=None, pdf=PDF, delay=0.0):
        self.answers, self.viewer, self.pdf, self.delay = list(answers), viewer, pdf, delay
        self.calls = []

    def __call__(self, _client, method, path, **kw):
        self.calls.append((method, path, kw))
        time.sleep(self.delay)
        if path == client.SEARCH_PATH and method == "GET":
            return Reply(SEARCH_PAGE)
        if path == client.CAPTCHA_PATH:
            return Reply(content=b"png")
        if path == client.SEARCH_PATH:
            return Reply(self.answers.pop(0) if len(self.answers) > 1 else self.answers[0])
        if path in client.KINDS.values():
            return Reply(self.viewer if self.viewer is not None else
                         '<iframe src="/SearchList/GetShowCertificateFileContent?QueryStringID=QUJD" height="100%" />')
        if path.startswith("/SearchList/GetShow"):
            return Reply(content=self.pdf)
        raise AssertionError(f"unexpected portal call {method} {path}")

    def posts(self):
        return [kw["data"] for m, p, kw in self.calls if m == "POST" and p == client.SEARCH_PATH]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    client._search.cache_clear()
    client._certificate.cache_clear()
    monkeypatch.setattr(client, "solve_captcha", lambda _img: "abcde")
    yield
    client._search.cache_clear()
    client._certificate.cache_clear()


def portal(monkeypatch, **kw):
    fake = FakePortal(**kw)
    monkeypatch.setattr(client, "_send", fake)
    return fake


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as exc:
        fn(*args, **kwargs)
    assert exc.value.user_message == user_message


def _app():
    app = FastAPI()
    app.include_router(rera_router.router)
    return TestClient(app)


def test_results_become_projects_with_their_certificates(monkeypatch):
    fake = portal(monkeypatch)
    r = client.search_projects(project_name="Sample")
    assert (r["total"], r["shown"]) == (2, 2)
    first, second = r["projects"]
    assert first["project"] == "Sample Heights" and first["promoter"] == "SAMPLE BUILDERS"
    assert first["last_modified"] == "19/05/2025"
    assert first["details_url"] == "https://rerait.telangana.gov.in/PrintPreview/PrintPreview?q=abc%2f1&x=1"
    assert [c["kind"] for c in first["certificates"]] == ["registration", "extension"]
    assert second["project"] == "Test Meadows & Villas"
    assert [c["kind"] for c in second["certificates"]] == ["registration", "special-extension"]
    form = fake.posts()[0]
    assert form["Project"] == "Sample" and form["Type"] == "Promoter" and form["PageSize"] == "50"
    assert form["Captcha"] == "ABCDE"  # the portal's captchas are capitals; OCR sometimes returns lower case
    assert form["__RequestVerificationToken"] == "tok1"


def test_wrong_captcha_is_retried_with_a_new_one(monkeypatch):
    fake = portal(monkeypatch, answers=(WRONG_CAPTCHA, WRONG_CAPTCHA, RESULTS))
    assert client.search_projects(project_name="Sample")["shown"] == 2
    assert len(fake.posts()) == 3
    assert sum(1 for m, p, _ in fake.calls if p == client.CAPTCHA_PATH) == 3


def test_captcha_gives_up_politely(monkeypatch):
    portal(monkeypatch, answers=(WRONG_CAPTCHA,))
    _raises(CAPTCHA_FAILED, client.search_projects, project_name="Sample")


def test_no_records_and_unexpected_pages(monkeypatch):
    portal(monkeypatch, answers=(NO_RECORDS,))
    _raises(NOT_FOUND, client.search_projects, project_name="Nothing Like This")
    client._search.cache_clear()
    portal(monkeypatch, answers=("<html>Service Unavailable</html>",))
    _raises(PORTAL_DOWN, client.search_projects, project_name="Sample")
    client._search.cache_clear()
    portal(monkeypatch, answers=(results_page([], 0),))
    _raises(NOT_FOUND, client.search_projects, project_name="Sample")


@pytest.mark.parametrize("fields", [
    {"project_name": "Sample<script>"}, {"project_name": "50% off"}, {"promoter_name": 'A "B" C'},
    {"project_name": "ab"}, {"project_name": "A" * 101}, {"promoter_name": "B" * 51},
    {"registration_no": "P0240-1224"}, {"registration_no": "P0240000122412345"}, {"registration_no": "P02<1"}, {},
])
def test_bad_input_never_reaches_the_portal(monkeypatch, fields):
    fake = portal(monkeypatch)
    _raises(BAD_INPUT, client.search_projects, **fields)
    assert fake.calls == []


def test_registration_number_and_names_are_tidied(monkeypatch):
    fake = portal(monkeypatch)
    client.search_projects(project_name="  Sample   Heights ", registration_no=" p02400001224 ")
    form = fake.posts()[0]
    assert (form["Project"], form["CertiNo"], form["Promoter"]) == ("Sample Heights", "P02400001224", "")


def test_identical_searches_share_one_portal_search(monkeypatch):
    fake = portal(monkeypatch, delay=0.05)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: client.search_projects(project_name="Sample"), range(8)))
    client.search_projects(project_name="Sample")  # a repeat later is served from the cache too
    assert len(fake.posts()) == 1 and all(r == results[0] for r in results)


def test_certificate_is_fetched_through_the_portal_viewer(monkeypatch):
    fake = portal(monkeypatch)
    pdf, name = client.fetch_certificate("registration", token(4242))
    assert pdf == PDF and name == "RERA-registration-certificate-4242.pdf"
    (m1, p1, kw1), (m2, p2, _) = fake.calls
    assert (m1, p1) == ("POST", "/SearchList/ShowCertificateIframe") and kw1["content"] == '{"ID": "%s"}' % token(4242)
    assert (m2, p2) == ("GET", "/SearchList/GetShowCertificateFileContent?QueryStringID=QUJD")


@pytest.mark.parametrize("bad", ["not base64!", base64.b64encode(b"ProjectID=1&evil=1").decode(),
                                 base64.b64encode(b'ProjectID=1"}, {"x": "y').decode(), token() + "&x=1", ""])
def test_forged_certificate_tokens_never_reach_the_portal(monkeypatch, bad):
    fake = portal(monkeypatch)
    _raises(BAD_INPUT, client.fetch_certificate, "registration", bad)
    _raises(BAD_INPUT, client.fetch_certificate, "everything", token())
    assert fake.calls == []


def test_only_the_portals_own_file_path_is_followed(monkeypatch):
    fake = portal(monkeypatch, viewer='<iframe src="https://evil.example/x.pdf"></iframe>')
    _raises(NOT_FOUND, client.fetch_certificate, "registration", token())
    assert [p for _, p, _ in fake.calls] == ["/SearchList/ShowCertificateIframe"]
    client._certificate.cache_clear()
    portal(monkeypatch, pdf=b"<html>error</html>")
    _raises(NOT_FOUND, client.fetch_certificate, "extension", token(ext="900"))


def test_the_bundled_intermediate_certificate_is_trusted():
    subjects = [dict(x[0] for x in c["subject"]).get("commonName") for c in client._SSL.get_ca_certs()]
    assert "emSign SSL CA - G1" in subjects


@pytest.mark.parametrize("message, status", [(BAD_INPUT, 400), (NOT_FOUND, 404), (CAPTCHA_FAILED, 503), (PORTAL_DOWN, 502)])
def test_routes_map_errors_as_plain_messages(monkeypatch, message, status):
    def fail(*_a, **_k):
        raise PortalError(message)

    monkeypatch.setattr(client, "search_projects", fail)
    monkeypatch.setattr(client, "fetch_certificate", fail)
    c = _app()
    r = c.post("/api/rera/search", json={"project_name": "Sample"})
    assert r.status_code == status and r.json()["detail"] == message
    r = c.get("/api/rera/certificate", params={"kind": "registration", "token": token()})  # shown in the page's preview
    assert r.status_code == status and r.json()["detail"] == message


def test_certificate_route_serves_the_pdf_inline(monkeypatch):
    portal(monkeypatch)
    r = _app().get("/api/rera/certificate", params={"kind": "registration", "token": token(77)})
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="RERA-registration-certificate-77.pdf"'
