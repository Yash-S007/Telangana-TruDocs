"""Each tool waits on its own threads (trudocs-state SKILL.md §10).

FastAPI runs every plain `def` route on one pool of 40 threads shared by the whole site, and a
route waiting on a slow portal holds its thread the whole time. So a crowd on one tool used to
stall every other tool and the page itself (measured: 40 GHMC searches at once froze the homepage
for 19.6 s, 60 RERA searches for 40 s). Routes wrapped with `ToolThreads.route` wait on their
tool's own threads instead, so a crowd only ever waits for its own tool.
"""
import functools
import inspect

import anyio


class ToolThreads:
    """
        _threads = ToolThreads()

        @router.post("/search")
        @_threads.route
        def search(req: SearchRequest): ...
    """

    def __init__(self, size: int = 40):  # what the whole site used to share
        self._limiter = anyio.CapacityLimiter(size)

    def route(self, fn):
        @functools.wraps(fn)
        async def endpoint(**kwargs):
            return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs), limiter=self._limiter)

        # FastAPI reads the route's parameters from here.
        endpoint.__signature__ = inspect.signature(fn, eval_str=True)
        return endpoint
