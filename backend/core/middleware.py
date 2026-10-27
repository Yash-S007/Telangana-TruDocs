"""Site-wide request handling that every tool shares."""
import logging
import os
import sys
import threading
import time
from collections import deque

from fastapi.responses import JSONResponse

log = logging.getLogger("trudocs.access")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    log.addHandler(_handler)
    log.propagate = False


class AccessLog:
    """One line per API request: method, the route's template (/api/cdma-tax/pdf/{ptin}, never the
    PTIN itself), status and time. No query string or body: those carry PTINs, survey and file numbers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        start, status = time.perf_counter(), 500

        async def send_and_note(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
        try:
            await self.app(scope, receive, send_and_note)
        finally:
            route = scope.get("route")
            log.info("%s %s %s %.0fms", scope["method"], route.path if route else "(not routed)", status,
                     (time.perf_counter() - start) * 1000)


SEARCHES_PER_MINUTE = 30
TOO_MANY = "Too many searches right now. Please wait a minute and try again."
_DOCUMENTS = ("/pdf", "/document", "/certificate", "/receipt", "/order", "/map/")


def client_ip(scope) -> str:
    """The visitor's address. Behind a proxy (Cloud Run: TRUST_PROXY_HOPS=1) it is the X-Forwarded-For
    entry the proxies added; anything left of it is whatever the visitor sent, so it isn't trusted."""
    hops = int(os.environ.get("TRUST_PROXY_HOPS", "0"))
    if hops:
        forwarded = dict(scope["headers"]).get(b"x-forwarded-for", b"").decode("latin-1")
        entries = [e.strip() for e in forwarded.split(",") if e.strip()]
        if len(entries) >= hops:
            return entries[-hops]
    return scope["client"][0] if scope.get("client") else ""


class PerPersonLimit:
    """At most SEARCHES_PER_MINUTE searches and documents a minute from one person, so one person or
    bot can't use up a government site's 60 requests a minute for everyone. Dropdown lists don't count.
    shortcut: counts live in this process; share them (e.g. Redis) before running more than one instance."""

    def __init__(self, app):
        self.app = app
        self._seen = {}
        self._lock = threading.Lock()

    def _allow(self, who: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._seen) > 10_000:  # forget people who have gone quiet
                self._seen = {k: t for k, t in self._seen.items() if t and now - t[-1] < 60}
            times = self._seen.setdefault(who, deque())
            while times and now - times[0] >= 60:
                times.popleft()
            if len(times) >= SEARCHES_PER_MINUTE:
                return False
            times.append(now)
            return True

    async def __call__(self, scope, receive, send):
        counted = scope["type"] == "http" and scope["path"].startswith("/api/") and (
            scope["method"] == "POST" or any(d in scope["path"] for d in _DOCUMENTS))
        if counted and not self._allow(client_ip(scope)):
            response = JSONResponse({"detail": TOO_MANY}, status_code=429, headers={"Retry-After": "60"})
            return await response(scope, receive, send)
        await self.app(scope, receive, send)
