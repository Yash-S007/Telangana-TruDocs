from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core import pdf
from backend.core.errors import PortalError
from backend.core.tool_threads import ToolThreads
from backend.scrapers.ghmc import mutation_client, property_tax_client

router = APIRouter(prefix="/api/ghmc", tags=["ghmc"])
# Each tool waits on its own threads, not the whole site's.
_mutation_threads = ToolThreads()
_tax_threads = ToolThreads()


def _http_error(exc: PortalError) -> HTTPException:
    return HTTPException(status_code=404 if "No record" in exc.user_message else 502, detail=exc.user_message)


class MutationRequest(BaseModel):
    assessment_number: str


@router.post("/mutation")
@_mutation_threads.route
def mutation_status(req: MutationRequest):
    try:
        return mutation_client.fetch_mutation_status(req.assessment_number)
    except PortalError as exc:
        raise _http_error(exc)


# The record as our PDF, which the page shows; POST like the search.
@router.post("/mutation/pdf")
@_mutation_threads.route
def mutation_pdf(req: MutationRequest):
    try:
        return pdf.response(*mutation_client.fetch_mutation_pdf(req.assessment_number))
    except PortalError as exc:
        raise _http_error(exc)


@router.get("/circles")
@_tax_threads.route
def circles():
    return property_tax_client.fetch_circles()


class PropertyTaxRequest(BaseModel):
    circle: str
    ptin: str = ""
    owner_name: str = ""
    door_no: str = ""


@router.post("/property-tax")
@_tax_threads.route
def property_tax(req: PropertyTaxRequest):
    try:
        return property_tax_client.fetch_property_tax(
            ptin=req.ptin, owner_name=req.owner_name, door_no=req.door_no, circle=req.circle
        )
    except PortalError as exc:
        raise _http_error(exc)


@router.post("/property-tax/pdf")
@_tax_threads.route
def property_tax_pdf(req: PropertyTaxRequest):
    try:
        return pdf.response(*property_tax_client.fetch_property_tax_pdf(
            ptin=req.ptin, owner_name=req.owner_name, door_no=req.door_no, circle=req.circle))
    except PortalError as exc:
        raise _http_error(exc)
