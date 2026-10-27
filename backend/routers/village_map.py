from fastapi import APIRouter, HTTPException

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.survey_map import client as survey_map_client
from backend.scrapers.village_map import client as village_map_client

router = APIRouter(prefix="/api/village-map", tags=["village-map"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, survey_map_client.NO_MAP: 404}


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


# The PDF loads into the page's preview, so errors are JSON like the map's.
@router.get("/pdf/{dmv}")
@_threads.route
def village_map_pdf(dmv: str):
    try:
        return pdf.response(*village_map_client.fetch_village_map_pdf(dmv))
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)
