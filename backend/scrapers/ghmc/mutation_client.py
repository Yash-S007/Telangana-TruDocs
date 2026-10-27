"""GHMC Mutation Status — classic ASP.NET WebForms full postback (no
ScriptManager/UpdatePanel on this page, confirmed by checking the page source
for those markers before writing this client).

Flow: GET the page once to seed __VIEWSTATE/__VIEWSTATEGENERATOR/
__EVENTVALIDATION, then POST the same fields back with the assessment number
filled in and the submit button's name/value included (ASP.NET WebForms
requires the clicked button's own form field to be present in the postback).
"""
import re

import httpx

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter
from backend.scrapers.ghmc.record_pdf import record_pdf

BASE_URL = "https://eodb.ghmc.gov.in"
PAGE_PATH = "/KnowYourMutationStatus_New.aspx"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal
_NUMBER_RE = re.compile(r"[0-9]{1,10}")  # GHMC's own number box: digits only, at most 10
DIGITS_ONLY = "An assessment number has only digits (at most 10), as on the property tax receipt."

_HIDDEN_FIELD_RE = re.compile(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*(?:value="([^"]*)")?[^>]*/?>')


def _extract_hidden_fields(html: str) -> dict:
    fields = {}
    for tag in re.findall(r'<input[^>]*type="hidden"[^>]*/?>', html, re.IGNORECASE):
        name_m = re.search(r'name="([^"]+)"', tag)
        value_m = re.search(r'value="([^"]*)"', tag)
        if name_m:
            fields[name_m.group(1)] = value_m.group(1) if value_m else ""
    return fields


def fetch_mutation_status(assessment_number: str) -> dict:
    if not assessment_number or not assessment_number.strip():
        raise PortalError(BAD_INPUT, "empty assessment number")
    if not _NUMBER_RE.fullmatch(assessment_number.strip()):
        raise PortalError(DIGITS_ONLY, "assessment number is not 1-10 digits")

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=20.0, follow_redirects=True) as client:
        try:
            _throttle.wait()
            get_resp = client.get(PAGE_PATH)
            get_resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise PortalError(PORTAL_DOWN, str(exc)) from exc

        hidden = _extract_hidden_fields(get_resp.text)
        payload = {
            **hidden,
            "ctl00$ContentPlaceHolder1$txtAssessmentNum": assessment_number.strip(),
            "ctl00$ContentPlaceHolder1$btn_submit": "Submit",
        }

        try:
            _throttle.wait()
            post_resp = client.post(PAGE_PATH, data=payload)
            post_resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise PortalError(PORTAL_DOWN, str(exc)) from exc

    return _parse_result(post_resp.text, assessment_number.strip())


def _parse_result(html: str, assessment_number: str) -> dict:
    lower = html.lower()
    if "no record" in lower or "not found" in lower or "invalid assessment" in lower:
        raise PortalError(NOT_FOUND, "portal reported no record")

    # The result renders inside the ContentPlaceHolder1 panel as a plain HTML
    # table/labels — extract every ASP.NET label span's text as a best-effort
    # normalized record. Precise field mapping is refined once we see a real
    # positive-match response (this scraper has not yet been tested against a
    # known-valid assessment number).
    labels = re.findall(
        r'<span[^>]*id="ContentPlaceHolder1_([a-zA-Z0-9_]+)"[^>]*>([^<]*)</span>',
        html,
    )
    record = {key: value.strip() for key, value in labels if value.strip()}

    return {
        "source": "ghmc_mutation_status",
        "assessment_number": assessment_number,
        "raw_fields": record,
        "found": bool(record),
    }


def fetch_mutation_pdf(assessment_number: str) -> tuple:
    """(pdf bytes, filename): the status the tool shows, as our PDF."""
    record = fetch_mutation_status(assessment_number)
    number = assessment_number.strip()
    return (record_pdf(record, title="GHMC Mutation Status", searched=f"Assessment No. {number}",
                       source="GHMC mutation status (eodb.ghmc.gov.in)"), pdf.filename("GHMC-mutation", number))
