from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PortalError
from backend.core.hierarchy import search_pattadar_villages
from backend.core.tool_threads import ToolThreads
from backend.scrapers.pattadar_passbook import client as pattadar_client

router = APIRouter(prefix="/api/pattadar", tags=["pattadar"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, CAPTCHA_FAILED: 503}


def _http_error(exc: PortalError) -> HTTPException:
    # CAPTCHA_FAILED is our OCR giving up, not the user's fault: 503 "try again".
    return HTTPException(status_code=_STATUS.get(exc.user_message, 502), detail=exc.user_message)


@router.get("/villages/search")
def villages_search(q: str = ""):
    return search_pattadar_villages(q)


@router.get("/survey-options/{village_id}")
@_threads.route
def survey_options(village_id: str):
    try:
        return pattadar_client.fetch_survey_options(village_id)
    except PortalError as exc:
        raise _http_error(exc)


@router.get("/khata-options/{village_id}")
@_threads.route
def khata_options(village_id: str, survey_no: str):
    try:
        return pattadar_client.fetch_khata_options(village_id, survey_no)
    except PortalError as exc:
        raise _http_error(exc)


class PattadarRequest(BaseModel):
    district_id: str
    mandal_id: str
    village_id: str
    survey_no: str
    khata_id: str


@router.post("/search")
@_threads.route
def search(req: PattadarRequest):
    try:
        return pattadar_client.fetch_pattadar_by_survey(
            district_id=req.district_id,
            mandal_id=req.mandal_id,
            village_id=req.village_id,
            survey_no=req.survey_no,
            khata_id=req.khata_id,
        )
    except PortalError as exc:
        raise _http_error(exc)


class PassbookRequest(BaseModel):
    passbook_no: str
    aadhaar_last4: str


@router.post("/search-by-passbook")
@_threads.route
def search_by_passbook(req: PassbookRequest):
    try:
        return pattadar_client.fetch_pattadar_by_passbook(
            passbook_no=req.passbook_no,
            aadhaar_last4=req.aadhaar_last4,
        )
    except PortalError as exc:
        raise _http_error(exc)
