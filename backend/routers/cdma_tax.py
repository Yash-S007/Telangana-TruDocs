from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.cdma_tax import client as cdma_tax_client

router = APIRouter(prefix="/api/cdma-tax", tags=["cdma-tax"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400}


def _status(exc: PortalError) -> int:
    return _STATUS.get(exc.user_message, 502)


@router.get("/towns")
def towns():
    return cdma_tax_client.towns()


class FindRequest(BaseModel):
    town_id: str
    door_no: str = ""
    owner_name: str = ""


# POST so owner names stay out of the access log (SKILL.md rule 3).
@router.post("/find")
@_threads.route
def find(req: FindRequest):
    try:
        return cdma_tax_client.find_properties(req.town_id, req.door_no, req.owner_name)
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)


class LookupRequest(BaseModel):
    ptin: str


@router.post("/property")
@_threads.route
def lookup(req: LookupRequest):
    try:
        return cdma_tax_client.fetch_property(req.ptin)
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)


@router.get("/receipt")
@_threads.route
def receipt(ptin: str, receipt_no: str, slno: str):
    try:
        pdf, filename = cdma_tax_client.fetch_receipt_pdf(ptin, receipt_no, slno)
    except PortalError as exc:
        # The PDF opens in a new tab, so a failure has to be a readable page, not JSON.
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>TruDocs Telangana</title><p style='font:16px sans-serif;padding:24px'>{escape(exc.user_message)}</p>",
            status_code=_status(exc),
        )
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
