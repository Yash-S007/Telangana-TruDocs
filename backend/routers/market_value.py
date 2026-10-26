from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.hierarchy import search_market_value_villages
from backend.scrapers.market_value import client as mv_client

router = APIRouter(prefix="/api/market-value", tags=["market-value"])

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, mv_client.NO_RATES: 404}


def _http_error(exc: PortalError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.user_message, 502), detail=exc.user_message)


@router.get("/villages/search")
def villages_search(q: str = ""):
    return search_market_value_villages(q)


@router.get("/hyderabad/divisions")
def hyderabad_divisions():
    try:
        return mv_client.fetch_hyderabad_divisions()
    except PortalError as exc:
        raise _http_error(exc)


@router.get("/hyderabad/localities")
def hyderabad_localities(division_id: str, q: str):
    try:
        return mv_client.search_hyderabad_localities(division_id, q)
    except PortalError as exc:
        raise _http_error(exc)


class MarketValueRequest(BaseModel):
    district_id: str
    mandal_id: str = ""
    mandal: str = ""
    village_id: str = ""
    village: str = ""
    division_id: str = ""
    locality_id: str = ""
    locality: str = ""


@router.post("/search")
def search(req: MarketValueRequest):
    try:
        return mv_client.fetch_rates(**req.model_dump())
    except PortalError as exc:
        raise _http_error(exc)
