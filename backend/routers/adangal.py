from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.errors import PortalError
from backend.core.hierarchy import search_adangal_villages
from backend.core.tool_threads import ToolThreads
from backend.scrapers.adangal import client as adangal_client

router = APIRouter(prefix="/api/adangal", tags=["adangal"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's


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
        raise HTTPException(status_code=404 if "No record" in exc.user_message else 502, detail=exc.user_message)
