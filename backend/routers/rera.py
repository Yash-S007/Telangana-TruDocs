from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core import pdf
from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.rera import client as rera_client

router = APIRouter(prefix="/api/rera", tags=["rera"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400, CAPTCHA_FAILED: 503, rera_client.NAME_CHARS: 400, rera_client.REG_NO_FORMAT: 400}


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


# The certificate loads into the page's preview, so errors are JSON like the search's.
@router.get("/certificate")
@_threads.route
def certificate(kind: str, token: str):
    try:
        return pdf.response(*rera_client.fetch_certificate(kind, token))
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)
