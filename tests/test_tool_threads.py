"""A crowd on one tool must not hold up the rest of the site (backend/core/tool_threads.py)."""
import asyncio
import threading
import time

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.core.tool_threads import ToolThreads


class Body(BaseModel):
    name: str


def test_wrapped_routes_keep_their_parameters_and_validation():
    app = FastAPI()
    threads = ToolThreads()

    @app.post("/search")
    @threads.route
    def search(req: Body, page: int = 1):
        return {"name": req.name, "page": page}

    client = TestClient(app)
    assert client.post("/search?page=2", json={"name": "x"}).json() == {"name": "x", "page": 2}
    assert client.post("/search", json={}).status_code == 422


def test_a_crowd_on_one_tool_does_not_block_the_rest_of_the_site():
    """60 searches stuck on a portal that doesn't answer (more than the 40 threads the whole
    site shares) while someone uses another route: it must still answer at once."""
    release = threading.Event()
    app = FastAPI()
    threads = ToolThreads()

    @app.get("/stuck")
    @threads.route
    def stuck():
        release.wait(10)
        return {}

    @app.get("/other")
    def other():  # a plain route on the shared threads, like the rest of the site
        return {"ok": True}

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30) as c:
            held = [asyncio.create_task(c.get("/stuck")) for _ in range(60)]
            await asyncio.sleep(0.4)  # everyone is waiting now
            t0 = time.perf_counter()
            probe = await c.get("/other")
            probe_ms = (time.perf_counter() - t0) * 1000
            release.set()
            codes = [r.status_code for r in await asyncio.gather(*held)]
            return probe.status_code, probe_ms, codes

    status, probe_ms, codes = asyncio.run(main())
    assert status == 200 and probe_ms < 250, f"other route took {probe_ms:.0f} ms while 60 searches waited"
    assert codes == [200] * 60
