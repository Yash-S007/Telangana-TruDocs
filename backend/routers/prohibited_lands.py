from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.hierarchy import search_prohibited_lands_villages
from backend.core.tool_threads import ToolThreads
from backend.scrapers.prohibited_lands import client as pl_client

router = APIRouter(prefix="/api/prohibited-lands", tags=["prohibited-lands"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, pl_client.NOT_PUBLISHED: 404}


def _http_error(exc: PortalError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.user_message, 502), detail=exc.user_message)


@router.get("/villages/search")
def villages_search(q: str = ""):
    return search_prohibited_lands_villages(q)


@router.get("/hyderabad/sros")
@_threads.route
def hyderabad_sros(division_id: str):
    try:
        return pl_client.fetch_hyderabad_sros(division_id)
    except PortalError as exc:
        raise _http_error(exc)


class Location(BaseModel):
    district_id: str
    mandal_id: str
    village_id: str
    sro_code: str = ""


class SurveyListRequest(Location):
    kind: str


@router.post("/categories")
@_threads.route
def categories(req: Location):
    try:
        return pl_client.fetch_categories(**req.model_dump())
    except PortalError as exc:
        raise _http_error(exc)


@router.post("/survey-list")
@_threads.route
def survey_list(req: SurveyListRequest):
    try:
        return pl_client.fetch_survey_list(**req.model_dump())
    except PortalError as exc:
        raise _http_error(exc)


# The official PDFs load into the page's preview, so errors are JSON like every other route.
@router.get("/pdf")
@_threads.route
def category_pdf(district_id: str, mandal_id: str, village_id: str, kind: str, formtype: str, sro_code: str = ""):
    try:
        return pdf.response(*pl_client.fetch_category_pdf(
            district_id=district_id, mandal_id=mandal_id, village_id=village_id,
            sro_code=sro_code, kind=kind, formtype=formtype,
        ))
    except PortalError as exc:
        raise _http_error(exc)


@router.get("/order")
@_threads.route
def order_pdf(order_id: str, flag: str, order_no: str = ""):
    try:
        return pdf.response(*pl_client.fetch_order_pdf(order_id, flag, order_no))
    except PortalError as exc:
        raise _http_error(exc)
