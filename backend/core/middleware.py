"""Site-wide request handling that every tool shares."""
import logging
import os
import sys
import time

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
            log.info("%s %s %s %.0fms", scope["method"], route.path if route else "(no such route)", status,
                     (time.perf_counter() - start) * 1000)
