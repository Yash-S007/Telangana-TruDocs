"""TG-bPASS Building Permission — the old TG-bPASS portal's public Citizen Search
(tgbpass.telangana.gov.in, API at backend.tsbpass.com). New applications moved to BuildNow in
December 2025 (login only); the old portal still answers for the ~3.1 lakh applications filed
before that, though its own banner says it closed.

No login, captcha or OTP. Only the public search is used:
  POST /api/v1/citizen_search/search_by_params   every filter is an EXACT match (any case). An
                                                 unknown key means NO filter (all 3 lakh, ~22 s),
                                                 so only the keys in _EMPTY are ever sent.
The portal's application detail page is deliberately NOT used: it exposes applicants' Aadhaar,
PAN and mobile numbers to anyone. The building facts are printed in the official letters anyway.
The official PDFs (permit order, work-commencement letter, …) are public files on the portal's
own S3 bucket; only links the portal's search returned for an application are ever fetched.
"""
import re
import time
from functools import lru_cache

import httpx

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter
from backend.core.single_flight import single_flight

BASE_URL = "https://backend.tsbpass.com"
SEARCH_PATH = "/api/v1/citizen_search/search_by_params"
DOCS_HOST = "certificates-tsbpass-prod.s3.ap-south-1.amazonaws.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal
# The portal stopped taking applications in December 2025, so a record barely changes. Its PDF
# links are signed for an hour, so those are fetched afresh, at most 15 minutes old.
_CACHE_SECONDS = 6 * 3600
_LINK_SECONDS = 15 * 60

_EMPTY = {"mobile_number": "", "application_identifier": "", "applicant_name": "", "ulb_name": "", "district_name": "",
          "authority_name": "", "circle_name": "", "mandal_name": "", "village_name": "", "application_type": "",
          "from_data": "", "to-date": "", "page_no": 1, "house": "", "survey_no": "", "locality": "", "plot_number": ""}
_FILE_RE = re.compile(r"[A-Z0-9][A-Z0-9/-]{4,39}")

STATUS = {"ACCEPTED": "Approved", "DEEMED": "Deemed approved", "FINAL_DEEMED": "Final deemed approval", "REJECTED": "Rejected",
          "CLOSED": "Closed", "SUBMITTED": "Submitted", "SHORTFALL": "Shortfall raised", "SHOW_CAUSE": "Show-cause notice issued",
          "REVOKED": "Revoked"}
APPLICATION_TYPE = {"SC": "Instant approval", "REG": "Instant registration", "OC": "Occupancy certificate", "SW": "Single window"}
APPROVAL_FOR = {"BUILDING": "Building", "OCCUPANCY": "Occupancy", "FINAL_LAYOUT": "Final layout"}
# The portal's names for an application's letters, in the order the preview offers them.
DOCUMENTS = {
    "WorkCommencement": "Letter of approval for commencement of work",
    "FinalDeemedWorkCommencement": "Final deemed approval",
    "DeemedWorkCommencement": "Deemed approval",
    "Acknowledgement": "Acknowledgement / building permit order",
    "Revocation": "Revocation order",
    "Showcause": "Show-cause notice",
    "ShortFall": "Shortfall notice",
    "FeeIntimation": "Fee intimation",
    "RevisedFee": "Revised fee intimation",
    "Correction": "Correction",
    "CorrectionReport": "Correction report",
    "CorrectionAcknowledgement": "Correction acknowledgement",
    "CorrectionRejection": "Correction rejection",
}


def _client(timeout: float = 60.0) -> httpx.Client:
    # Connect once more if a new connection is dropped mid-handshake; nothing is sent twice.
    return httpx.Client(base_url=BASE_URL, timeout=timeout, transport=httpx.HTTPTransport(retries=1),
                        headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Origin": "https://tgbpass.telangana.gov.in",
                                 "Referer": "https://tgbpass.telangana.gov.in/"})


def _call(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    try:
        _throttle.wait()
        resp = client.request(method, path, **kwargs)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:  # ValueError: not JSON (an error page)
        raise PortalError(PORTAL_DOWN, str(exc)) from exc
    if not isinstance(data, dict) or not data.get("success") or not isinstance(data.get("data"), dict):
        raise PortalError(PORTAL_DOWN, "unexpected reply")
    return data["data"]


def _search(**filters) -> dict:
    with _client() as client:
        data = _call(client, "POST", SEARCH_PATH, json={**_EMPTY, **filters})
    apps, pages = data.get("applications"), data.get("pagination_info") or {}
    if not isinstance(apps, list):
        raise PortalError(PORTAL_DOWN, "search reply without applications")
    return {"applications": apps, "total": int(pages.get("total_count") or 0)}


def _summary(a: dict) -> dict:
    """The application's status and place; nothing about the applicant."""
    status = a.get("status") or ""
    decided = status in ("ACCEPTED", "REJECTED", "CLOSED", "DEEMED", "FINAL_DEEMED")
    return {
        "file_no": a.get("application_id") or "",
        "status": STATUS.get(status, status.replace("_", " ").title()),
        "approval_for": APPROVAL_FOR.get(a.get("approval_for"), (a.get("approval_for") or "").title()),
        "type": APPLICATION_TYPE.get(a.get("application_type"), a.get("application_type") or ""),
        "town": a.get("ulb") or "",
        "district": a.get("district_name") or "",
        "survey_no": (a.get("survey_no") or "").strip(),
        "plot_no": (a.get("plot_no") or "").strip(),
        "locality": (a.get("locality") or "").strip(),
        "applied_on": (a.get("applied_on") or a.get("created_at") or "")[:10],
        "decided_on": (a.get("completed_date") or "")[:10] if decided else "",
    }


def _documents(certificates) -> dict:
    """kind → link, for the letters the portal holds; only its own bucket's links are kept."""
    if not isinstance(certificates, dict):
        return {}
    return {k: u for k, u in certificates.items()
            if k in DOCUMENTS and isinstance(u, str) and re.match(rf"https://{re.escape(DOCS_HOST)}/[\w./%-]+\.pdf(\?\S*)?$", u, re.I)}


def fetch_application(file_no: str) -> dict:
    """An application's status and the official letters the portal holds for it."""
    file_no = (file_no or "").strip().upper()
    if not _FILE_RE.fullmatch(file_no):
        raise PortalError(BAD_INPUT, "a file number looks like 510537/GHMC/0049/2025")
    bucket = int(time.time() // _CACHE_SECONDS)
    return single_flight(("bpass", file_no, bucket), lambda: _application(file_no, bucket))


# shortcut: per-process cache (6-hour buckets); move to Redis if we run more than one instance.
# It holds no document links: those are signed for an hour (see _links).
@lru_cache(maxsize=256)
def _application(file_no: str, _bucket: int) -> dict:
    a = _match(file_no)
    if a is None:
        raise PortalError(NOT_FOUND, "no application with this file number")
    documents = _documents(a.get("certificates"))
    return {
        "source": "tg_bpass",
        "found": True,
        **_summary(a),
        "documents": [{"kind": k, "label": DOCUMENTS[k]} for k in DOCUMENTS if k in documents],
    }


def _match(file_no: str):
    """The search result for exactly this file number, or None."""
    return next((a for a in _search(application_identifier=file_no)["applications"]
                 if (a.get("application_id") or "").upper() == file_no), None)


def fetch_document(file_no: str, kind: str) -> tuple:
    """(pdf bytes, filename): one of the official letters the portal holds for this application."""
    if kind not in DOCUMENTS:
        raise PortalError(BAD_INPUT, "unknown document")
    result = fetch_application(file_no)
    if kind not in {d["kind"] for d in result["documents"]}:
        raise PortalError(NOT_FOUND, "the portal has no such document for this application")
    key = (result["file_no"], kind, int(time.time() // _CACHE_SECONDS))
    return single_flight(("bpass-doc",) + key, lambda: _document(*key))


@lru_cache(maxsize=256)
def _links(file_no: str, _bucket: int) -> dict:
    """Fresh signed links to an application's letters (each lasts an hour)."""
    a = _match(file_no)
    return _documents(a.get("certificates")) if a else {}


# shortcut: keeps the last 32 letters (~300 KB each) for 6 hours; move to disk if many people
# open the same letters. Kept with the front page, so everyone asking for one shares one copy.
@lru_cache(maxsize=32)
def _document(file_no: str, kind: str, _bucket: int) -> tuple:
    link = _links(file_no, int(time.time() // _LINK_SECONDS)).get(kind)
    if not link:
        raise PortalError(NOT_FOUND, "the portal has no such document for this application")
    try:
        with _client() as client:  # an absolute link: the portal's own bucket, not its API
            resp = client.get(link)
            resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PortalError(PORTAL_DOWN, str(exc)) from exc
    if not resp.content.startswith(b"%PDF"):
        raise PortalError(PORTAL_DOWN, "the portal's document is not a PDF")
    return pdf.document(resp.content, "Building Permission (TG-bPASS)", f"File No. {file_no}", DOCUMENTS[kind])
