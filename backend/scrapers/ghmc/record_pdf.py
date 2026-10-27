"""A GHMC record as our PDF. Both GHMC pages are ASP.NET, read as label id → value, so the ids are
made readable as the page showed them ("lblOwnerName" → "Owner Name")."""
import re

from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from backend.core import pdf
from backend.core.errors import NOT_FOUND, PortalError

_KNOWN_LABELS = {"ptinno": "PTIN Number", "owner": "Owner Name", "door": "Door Number", "assessmentnum": "Assessment Number"}


def field_label(key: str) -> str:
    bare = re.sub(r"^(grd_SearchResult_|ContentPlaceHolder1_)", "", key, flags=re.I)
    bare = re.sub(r"_\d+$", "", re.sub(r"^lbl", "", bare, flags=re.I))
    if bare.lower() in _KNOWN_LABELS:
        return _KNOWN_LABELS[bare.lower()]
    spaced = re.sub(r"[_-]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", bare)).strip()
    return spaced[:1].upper() + spaced[1:] if spaced else key


def record_pdf(record: dict, *, title: str, searched: str, source: str) -> bytes:
    if not record["found"]:
        raise PortalError(NOT_FOUND, "portal page had no record fields")
    return pdf.build([pdf.para(title, "title"), pdf.para(searched, "sub"), Spacer(0, 5 * mm),
                      pdf.fields((field_label(k), v) for k, v in record["raw_fields"].items())],
                     title=f"{title}: {searched}", note="For reference only: not an official GHMC document.", source=source)
