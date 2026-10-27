import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware

from backend.core.middleware import AccessLog, BodyLimit, PerPersonLimit
from backend.routers import adangal, bpass, cdma_tax, ghmc, health, hydra_ftl, market_value, pattadar_passbook, prohibited_lands, rera, survey_map, village_map

logger = logging.getLogger(__name__)
# httpx logs every portal URL at INFO, and the passbook search puts the passbook number
# and Aadhaar digits in its URL — keep those out of logs even when INFO is switched on.
logging.getLogger("httpx").setLevel(logging.WARNING)
# uvicorn's access log prints every URL, and some carry a PTIN, a file or a survey number;
# AccessLog prints the route's template instead.
logging.getLogger("uvicorn.access").disabled = True


def _prewarm_caches() -> None:
    """Pre-populate district caches in a background thread at startup.

    Both scrapers cache district lists with lru_cache — they never change
    at runtime, but each cold call to a government Java server can take
    30+ seconds. Pre-warming here means the first real user request finds
    the cache already hot instead of waiting on a live round-trip.
    Failures are logged and suppressed so a slow/down portal at startup
    doesn't prevent the app from serving GHMC routes that need no cascade.
    """
    from backend.scrapers.pattadar_passbook import client as pattadar_client
    from backend.scrapers.adangal import client as adangal_client

    for name, fn in [
        ("pattadar districts", pattadar_client.fetch_districts),
        ("adangal districts", adangal_client.fetch_districts),
    ]:
        try:
            result = fn()
            logger.info("cache prewarm: %s → %d items", name, len(result))
        except Exception as exc:
            logger.warning("cache prewarm failed for %s (will retry on first user request): %s", name, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_prewarm_caches, daemon=True, name="cache-prewarm").start()
    yield


app = FastAPI(title="Telangana TruDocs API", version="0.1.0", lifespan=lifespan)
# Scripts and styles shrink to about a quarter (first load 594 → 137 KB, the PDF viewer 2.6 → 0.6 MB).
# PDFs are already compressed, so they're sent as they are.
app.add_middleware(GZipMiddleware, compresslevel=6, exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + ("application/pdf",))
app.add_middleware(PerPersonLimit)
app.add_middleware(BodyLimit)
app.add_middleware(AccessLog)  # added last = runs first, so it also logs the limit's 429s

# CORS — always allow localhost dev server; add any production origins from env.
_extra_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"] + _extra_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(ghmc.router)
app.include_router(cdma_tax.router)
app.include_router(bpass.router)
app.include_router(adangal.router)
app.include_router(pattadar_passbook.router)
app.include_router(market_value.router)
app.include_router(prohibited_lands.router)
app.include_router(survey_map.router)
app.include_router(rera.router)
app.include_router(village_map.router)
app.include_router(hydra_ftl.router)

# Static frontend mount MUST come last so /api/* routes above always win.
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
