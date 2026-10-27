from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.hierarchy import search_survey_map_villages
from backend.core.tool_threads import ToolThreads
from backend.scrapers.survey_map import client as survey_map_client
from backend.scrapers.survey_map import pdf as survey_map_pdf

router = APIRouter(prefix="/api/survey-map", tags=["survey-map"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400}


def _http_error(exc: PortalError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.user_message, 502), detail=exc.user_message)


@router.get("/villages/search")
def villages_search(q: str = ""):
    return search_survey_map_villages(q)


@router.get("/survey-options/{dmv}")
@_threads.route
def survey_options(dmv: str):
    try:
        return survey_map_client.fetch_survey_options(dmv)
    except PortalError as exc:
        raise _http_error(exc)


class ParcelRequest(BaseModel):
    dmv: str
    survey_no: str


# POST so the survey number stays out of the access log (SKILL.md rule 3).
@router.post("/parcel")
@_threads.route
def parcel(req: ParcelRequest):
    try:
        return survey_map_client.fetch_parcel(req.dmv, req.survey_no)
    except PortalError as exc:
        raise _http_error(exc)


# The page shows this PDF of the map; POST like /parcel.
@router.post("/pdf")
@_threads.route
def parcel_pdf(req: ParcelRequest):
    try:
        return pdf.response(*survey_map_pdf.fetch_parcel_pdf(req.dmv, req.survey_no))
    except PortalError as exc:
        raise _http_error(exc)
