from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.rera import client as rera_client

router = APIRouter(prefix="/api/rera", tags=["rera"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, CAPTCHA_FAILED: 503}


def _status(exc: PortalError) -> int:
    return _STATUS.get(exc.user_message, 502)


class SearchRequest(BaseModel):
    project_name: str = ""
    promoter_name: str = ""
    registration_no: str = ""


# POST so promoter names (often a person's name) stay out of the access log (SKILL.md rule 3).
@router.post("/search")
@_threads.route
def search(req: SearchRequest):
    try:
        return rera_client.search_projects(req.project_name, req.promoter_name, req.registration_no)
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)


@router.get("/certificate")
@_threads.route
def certificate(kind: str, token: str):
    try:
        pdf, filename = rera_client.fetch_certificate(kind, token)
    except PortalError as exc:
        # The PDF opens in a new tab, so a failure has to be a readable page, not JSON.
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>TruDocs Telangana</title><p style='font:16px sans-serif;padding:24px'>{escape(exc.user_message)}</p>",
            status_code=_status(exc),
        )
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
