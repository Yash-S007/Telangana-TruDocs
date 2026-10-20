from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.village_map import client as village_map_client

router = APIRouter(prefix="/api/village-map", tags=["village-map"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400}


def _status(exc: PortalError) -> int:
    return _STATUS.get(exc.user_message, 502)


# The village search is Survey Map's (/api/survey-map/villages/search): same village list.
@router.get("/map/{dmv}")
@_threads.route
def village_map(dmv: str):
    try:
        return village_map_client.fetch_village_map(dmv)
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)


@router.get("/pdf/{dmv}")
@_threads.route
def village_map_pdf(dmv: str):
    try:
        pdf, filename = village_map_client.fetch_village_map_pdf(dmv)
    except PortalError as exc:
        # The PDF opens in a new tab, so a failure has to be a readable page, not JSON.
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>TruDocs Telangana</title><p style='font:16px sans-serif;padding:24px'>{escape(exc.user_message)}</p>",
            status_code=_status(exc),
        )
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
