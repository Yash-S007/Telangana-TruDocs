from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.hydra_ftl import client as hydra_client

router = APIRouter(prefix="/api/hydra-ftl", tags=["hydra-ftl"])
_threads = ToolThreads()  # this tool waits on its own threads, not the whole site's

_STATUS = {NOT_FOUND: 404, BAD_INPUT: 400}


def _call(fn, *args):
    try:
        return fn(*args)
    except PortalError as exc:
        raise HTTPException(status_code=_STATUS.get(exc.user_message, 502), detail=exc.user_message)


@router.get("/places")
@_threads.route
def places():
    return _call(hydra_client.fetch_places)


@router.get("/lakes")
@_threads.route
def lakes(district: str = "", mandal: str = "", village: str = "", q: str = ""):
    return _call(hydra_client.find_lakes, district, mandal, village, q)


@router.get("/lake")
@_threads.route
def lake(key: str):
    return _call(hydra_client.fetch_lake, key)


# An official PDF, loaded into the page's PDF preview, so errors are JSON like the rest.
@router.get("/document")
@_threads.route
def document(key: str, kind: str):
    pdf, filename = _call(hydra_client.fetch_document, key, kind)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})
