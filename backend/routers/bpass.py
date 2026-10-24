from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.bpass import client as bpass_client

router = APIRouter(prefix="/api/bpass", tags=["bpass"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400}


def _status(exc: PortalError) -> int:
    return _STATUS.get(exc.user_message, 502)


class ApplicationRequest(BaseModel):
    file_no: str


@router.post("/application")
@_threads.route
def application(req: ApplicationRequest):
    try:
        return bpass_client.fetch_application(req.file_no)
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)


# An official letter, loaded into the page's PDF preview, so errors are JSON like the rest.
@router.get("/document")
@_threads.route
def document(file_no: str, kind: str):
    try:
        pdf, filename = bpass_client.fetch_document(file_no, kind)
    except PortalError as exc:
        raise HTTPException(status_code=_status(exc), detail=exc.user_message)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
