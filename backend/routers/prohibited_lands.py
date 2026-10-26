from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.hierarchy import search_prohibited_lands_villages
from backend.scrapers.prohibited_lands import client as pl_client

router = APIRouter(prefix="/api/prohibited-lands", tags=["prohibited-lands"])

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, pl_client.NOT_PUBLISHED: 404}


def _status(exc: PortalError) -> int:
    return _STATUS.get(exc.user_message, 502)


def _http_error(exc: PortalError) -> HTTPException:
    return HTTPException(status_code=_status(exc), detail=exc.user_message)


def _pdf(content: bytes, filename: str) -> Response:
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


def _pdf_error_page(exc: PortalError) -> HTMLResponse:
    # PDFs open in a new tab, so a failure has to be a readable page, not JSON.
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>TruDocs Telangana</title><p style='font:16px sans-serif;padding:24px'>{escape(exc.user_message)}</p>",
        status_code=_status(exc),
    )


@router.get("/villages/search")
def villages_search(q: str = ""):
    return search_prohibited_lands_villages(q)


@router.get("/hyderabad/sros")
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
def categories(req: Location):
    try:
        return pl_client.fetch_categories(**req.model_dump())
    except PortalError as exc:
        raise _http_error(exc)


@router.post("/survey-list")
def survey_list(req: SurveyListRequest):
    try:
        return pl_client.fetch_survey_list(**req.model_dump())
    except PortalError as exc:
        raise _http_error(exc)


@router.get("/pdf")
def category_pdf(district_id: str, mandal_id: str, village_id: str, kind: str, formtype: str, sro_code: str = ""):
    try:
        return _pdf(*pl_client.fetch_category_pdf(
            district_id=district_id, mandal_id=mandal_id, village_id=village_id,
            sro_code=sro_code, kind=kind, formtype=formtype,
        ))
    except PortalError as exc:
        return _pdf_error_page(exc)


@router.get("/order")
def order_pdf(order_id: str, flag: str):
    try:
        return _pdf(*pl_client.fetch_order_pdf(order_id, flag))
    except PortalError as exc:
        return _pdf_error_page(exc)
