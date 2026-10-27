from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.hierarchy import search_adangal_villages
from backend.core.tool_threads import ToolThreads
from backend.scrapers.adangal import client as adangal_client

router = APIRouter(prefix="/api/adangal", tags=["adangal"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400}


def _http_error(exc: PortalError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.user_message, 502), detail=exc.user_message)


@router.get("/villages/search")
def villages_search(q: str = ""):
    return search_adangal_villages(q)


@router.get("/survey-options/{village_id}")
@_threads.route
def survey_options(village_id: str, option: str = "surveyNo"):
    return adangal_client.fetch_survey_options(village_id, option)


class AdangalRequest(BaseModel):
    district_id: str
    division_id: str
    mandal_id: str
    village_id: str
    survey_or_khata_value: str
    option: str = "surveyNo"


@router.post("/search")
@_threads.route
def search(req: AdangalRequest):
    try:
        return adangal_client.fetch_adangal(
            district_id=req.district_id,
            division_id=req.division_id,
            mandal_id=req.mandal_id,
            village_id=req.village_id,
            survey_or_khata_value=req.survey_or_khata_value,
            option=req.option,
        )
    except PortalError as exc:
        raise _http_error(exc)


# Our PDF of the Pahani, which the page shows. POST like the search, so nothing searched is in the
# access log.
@router.post("/pdf")
@_threads.route
def pahani_pdf(req: AdangalRequest):
    try:
        return pdf.response(*adangal_client.fetch_adangal_pdf(**req.model_dump()))
    except PortalError as exc:
        raise _http_error(exc)
