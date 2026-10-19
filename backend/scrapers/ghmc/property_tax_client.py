"""GHMC Property Tax Search — ASP.NET WebForms. The page has a ScriptManager
present, but the search submit button (oddly named `btnsubmitotp` in the
markup — a leftover name, not an actual OTP requirement: its onclick is a
plain client-side `validate()`, and no OTP/captcha field exists anywhere on
the page) is tested here as a classic full postback first, same shape as
Mutation Status.

Search modes: PTIN (assessment number), or Owner Name + Circle, or Door
Number + Circle. Circle list (61) is static/server-rendered — no scrape
needed, hand-seed from the confirmed page HTML.
"""
import re
from functools import lru_cache

import httpx

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter

BASE_URL = "https://www.ghmc.gov.in"
PAGE_PATH = "/Search.aspx"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal


def _extract_hidden_fields(html: str) -> dict:
    fields = {}
    for tag in re.findall(r'<input[^>]*type="hidden"[^>]*/?>', html, re.IGNORECASE):
        name_m = re.search(r'name="([^"]+)"', tag)
        value_m = re.search(r'value="([^"]*)"', tag)
        if name_m:
            fields[name_m.group(1)] = value_m.group(1) if value_m else ""
    return fields


def _parse_circles(html: str) -> list:
    match = re.search(r'<select name="ctl00\$ContentPlaceHolder1\$ddlcircle"[^>]*>(.*?)</select>', html, re.S)
    if not match:
        return []
    options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', match.group(1))
    return [{"value": v, "label": t.strip()} for v, t in options if v]


@lru_cache(maxsize=1)
def _fetch_circles_cached() -> list:
    # GHMC's 61 municipal circles are static — never change at runtime, and
    # are the same for every user, so cache rather than re-fetch the whole
    # Search.aspx page on every request just to read this one dropdown.
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0) as client:
        _throttle.wait()
        html = client.get(BASE_URL + PAGE_PATH).text
    return _parse_circles(html)


def fetch_circles(html: str = None) -> list:
    """Parse the static circle dropdown. Pass cached HTML, or None to use the
    cached live fetch."""
    if html is not None:
        return _parse_circles(html)
    return _fetch_circles_cached()


def fetch_property_tax(*, ptin: str = "", owner_name: str = "", door_no: str = "", circle: str = "") -> dict:
    # Confirmed live: the portal's server-side validation rejects the search
    # with "Please select any circle here" even for a PTIN-only search — circle
    # is mandatory for every search mode on this form, not just owner/door.
    if not circle:
        raise PortalError(BAD_INPUT, "circle is required")
    if not any([ptin, owner_name, door_no]):
        raise PortalError(BAD_INPUT, "at least one of ptin/owner_name/door_no is required")

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
            "ctl00$ContentPlaceHolder1$ddlcircle": circle,
            "ctl00$ContentPlaceHolder1$txtptinno": ptin.strip(),
            "ctl00$ContentPlaceHolder1$txtowner": owner_name.strip(),
            "ctl00$ContentPlaceHolder1$txtdoorno": door_no.strip(),
            "ctl00$ContentPlaceHolder1$btnsubmitotp": "Submit",
        }

        try:
            _throttle.wait()
            post_resp = client.post(PAGE_PATH, data=payload)
            post_resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise PortalError(PORTAL_DOWN, str(exc)) from exc

    return _parse_result(post_resp.text, ptin or door_no or owner_name)


def _parse_result(html: str, query: str) -> dict:
    lower = html.lower()
    if "no record" in lower or "not found" in lower or "no data" in lower:
        raise PortalError(NOT_FOUND, "portal reported no record")

    labels = re.findall(
        r'<span[^>]*id="ContentPlaceHolder1_([a-zA-Z0-9_]+)"[^>]*>([^<]*)</span>',
        html,
    )
    record = {key: value.strip() for key, value in labels if value.strip()}

    return {
        "source": "ghmc_property_tax",
        "query": query,
        "raw_fields": record,
        "found": bool(record),
    }
