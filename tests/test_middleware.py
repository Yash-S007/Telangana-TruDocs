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
    assert lines[1].startswith("GET (no such route) 404 ")
    assert len(lines) == 2  # only API requests
    assert not any(n in line for line in lines for n in ("1113999001", "043700", "9999999999"))


def test_the_app_uses_it_and_silences_uvicorns_url_log():
    from backend.main import app
    assert any(m.cls is middleware.AccessLog for m in app.user_middleware)
    assert logging.getLogger("uvicorn.access").disabled
