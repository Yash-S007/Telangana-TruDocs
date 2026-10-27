"""Site-wide request handling (backend/core/middleware.py). Made-up values; no network."""
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import middleware


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _logged(monkeypatch, *requests):
    app = FastAPI()
    app.add_middleware(middleware.AccessLog)

    @app.get("/api/sample/pdf/{ptin}")
    def pdf(ptin: str, receipt_no: str = ""):
        return {"ok": True}

    lines = Lines()
    monkeypatch.setattr(middleware.log, "handlers", [lines])
    client = TestClient(app)
    for path in requests:
        client.get(path)
    return lines.lines


def test_access_log_names_the_route_not_the_numbers_in_it(monkeypatch):
    lines = _logged(monkeypatch, "/api/sample/pdf/1113999001?receipt_no=043700", "/api/nothing/9999999999", "/index.html")
    assert lines[0].startswith("GET /api/sample/pdf/{ptin} 200 ") and lines[0].endswith("ms")
    assert lines[1].startswith("GET (not routed) 404 ")
    assert len(lines) == 2  # only API requests
    assert not any(n in line for line in lines for n in ("1113999001", "043700", "9999999999"))


def test_the_app_uses_it_and_silences_uvicorns_url_log():
    from backend.main import app
    assert any(m.cls is middleware.AccessLog for m in app.user_middleware)
    assert logging.getLogger("uvicorn.access").disabled


def _limited_app(monkeypatch):
    app = FastAPI()
    app.add_middleware(middleware.PerPersonLimit)

    @app.post("/api/sample/search")
    def search():
        return {"ok": True}

    @app.get("/api/sample/pdf/{n}")
    def pdf(n: str):
        return {"ok": True}

    @app.get("/api/sample/survey-options/{n}")
    def options(n: str):
        return []
    return app


def test_one_person_gets_30_searches_a_minute_lists_dont_count(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(middleware.time, "monotonic", lambda: now[0])
    monkeypatch.setenv("TRUST_PROXY_HOPS", "1")
    client = TestClient(_limited_app(monkeypatch))
    me, other = {"X-Forwarded-For": "203.0.113.7"}, {"X-Forwarded-For": "198.51.100.9"}
    for i in range(30):
        path = "/api/sample/pdf/1" if i % 2 else "/api/sample/search"
        r = client.post(path, headers=me) if path.endswith("search") else client.get(path, headers=me)
        assert r.status_code == 200, i
    assert client.get("/api/sample/survey-options/1", headers=me).status_code == 200  # lists don't count
    r = client.post("/api/sample/search", headers=me)
    assert r.status_code == 429 and r.json() == {"detail": middleware.TOO_MANY} and r.headers["retry-after"] == "60"
    assert client.post("/api/sample/search", headers=other).status_code == 200  # someone else is not held up
    # a visitor can't dodge it by sending their own X-Forwarded-For: the proxy's entry is the last one
    assert client.post("/api/sample/search", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.7"}).status_code == 429
    now[0] += 60
    assert client.post("/api/sample/search", headers=me).status_code == 200  # a minute later


def test_client_ip_trusts_only_the_proxys_entries(monkeypatch):
    scope = {"client": ("10.0.0.1", 5000), "headers": [(b"x-forwarded-for", b"1.1.1.1, 203.0.113.7, 35.0.0.1")]}
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    assert middleware.client_ip(scope) == "10.0.0.1"  # no proxy configured: the connection's address
    monkeypatch.setenv("TRUST_PROXY_HOPS", "1")
    assert middleware.client_ip(scope) == "35.0.0.1"
    monkeypatch.setenv("TRUST_PROXY_HOPS", "2")  # e.g. a Google load balancer in front of Cloud Run
    assert middleware.client_ip(scope) == "203.0.113.7"
    monkeypatch.setenv("TRUST_PROXY_HOPS", "5")  # fewer entries than hops: misconfigured, don't trust the header
    assert middleware.client_ip(scope) == "10.0.0.1"
