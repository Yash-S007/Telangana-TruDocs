"""Market Value (Unit Rates) — registration.telangana.gov.in/UnitRateMV, Java.

Confirmed live (2026-10-15) by reading the page JS and replaying it:
- Public: no login, no captcha, no OTP, and no session cookie needed — every
  call below works on its own.
- District → Mandal → Village cascade is plain GETs that return text like
  "01/ABDULLAPURMET##02/AMANGAL##", not <option> HTML.
- Hyderabad (district 16_1) has no mandals/villages. Its localities come from
  getLocationDetails?codes=<district>~<text>~$~$~<division> in the same format,
  and the division is required (empty → the portal's own 404 / "Error Msg").
- The search is a full form POST to /UnitRateMV/unitRateMV. The page's JS also
  sends every field again as base64(JSON) in `encodestr`; we send both, exactly
  like the browser.
- The "Apartment Value" option (search_by=A) returns the portal's own 404, and
  the apartment-rate and classification columns of the result are commented out
  in the HTML — the portal no longer shows them, so neither do we.
"""
import base64
import json
import re
import threading
import time
from functools import lru_cache
from html import unescape

import httpx

from backend.core.errors import BAD_INPUT, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter

BASE_URL = "https://registration.telangana.gov.in"
LANDING_PATH = "/UnitRateMV/getDistrictList.htm"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HYDERABAD = "16_1"

# A rates table with no rows: the user picked a real place, so don't say "check your details".
NO_RATES = "The department hasn't published market value rates for this place."

# At most two portal requests a second (the GHMC and Pattadar clients use the same gap).
_throttle = RateLimiter(min_interval_seconds=0.5)

_CACHE_SECONDS = 6 * 3600
# Identical searches that arrive together wait for one portal fetch instead of each
# making their own. Striped locks keep this bounded; two different searches only
# share a lock 1 time in 32.
_LOCKS = [threading.Lock() for _ in range(32)]

# Checked before anything reaches the portal. The locality text also can't
# contain "~", which is the field separator inside `codes`.
_DISTRICT_RE = re.compile(r"\d{1,3}_\d{1,2}")
_CODE_RE = re.compile(r"\d{1,10}")
_LOCALITY_QUERY_RE = re.compile(r"[A-Za-z0-9 .\-]{3,50}")
_MAX_NAME = 120


def _client(timeout: float = 45.0) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT, "Referer": BASE_URL + LANDING_PATH},
        timeout=timeout,
        follow_redirects=True,
    )


def _get(client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
    try:
        _throttle.wait()
        resp = client.get(path, params=params)
        resp.raise_for_status()
        return resp
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PortalError(PORTAL_DOWN, str(exc)) from exc


def _post(client: httpx.Client, path: str, data: dict) -> httpx.Response:
    try:
        _throttle.wait()
        resp = client.post(path, data=data)
        resp.raise_for_status()
        return resp
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PortalError(PORTAL_DOWN, str(exc)) from exc


def _require(value: str, pattern: re.Pattern, what: str) -> str:
    value = (value or "").strip()
    if not pattern.fullmatch(value):
        raise PortalError(BAD_INPUT, f"invalid {what}")
    return value


def _require_name(value: str, what: str) -> str:
    value = " ".join((value or "").split())
    if not value or len(value) > _MAX_NAME:
        raise PortalError(BAD_INPUT, f"invalid {what}")
    return value


def _parse_pairs(text: str) -> list:
    """'01/ABDULLAPURMET##02/AMANGAL##' → [{"value": "01", "label": "ABDULLAPURMET"}, …].

    Mirrors the page's JS exactly — it keeps only the text between the first and
    second "/" and the browser collapses its whitespace — because the label is
    sent back to the portal as-is on submit."""
    if text.strip() in ("Malicious", "Special"):
        raise PortalError(BAD_INPUT, f"portal flagged the input as {text.strip()}")
    items = []
    for chunk in text.split("##"):
        parts = chunk.split("/")
        if len(parts) >= 2 and parts[0].strip():
            items.append({"value": parts[0].strip(), "label": " ".join(parts[1].split())})
    return items


def _select_options(html: str, name: str) -> list:
    m = re.search(rf'<select[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return []
    options = re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]*)', m.group(1))
    return [{"value": v, "label": " ".join(t.split())} for v, t in options]


def _landing_options(name: str) -> list:
    with _client() as client:
        html = _get(client, LANDING_PATH).text
    options = _select_options(html, name)
    if not options:
        # Raise rather than return [] so lru_cache doesn't keep an empty list forever.
        raise PortalError(PORTAL_DOWN, f"no <select name={name}> options on the page")
    return options


# Districts and Hyderabad divisions are server-rendered on the landing page and
# are static for the life of the process.


@lru_cache(maxsize=1)
def fetch_districts() -> list:
    return _landing_options("districtId")


@lru_cache(maxsize=1)
def fetch_hyderabad_divisions() -> list:
    return _landing_options("divCode")


def fetch_mandals(district_id: str) -> list:
    district_id = _require(district_id, _DISTRICT_RE, "district")
    with _client() as client:
        resp = _get(client, "/UnitRateMV/getMandalListByDistCode", {"districtcode": district_id})
    return _parse_pairs(resp.text)


def fetch_villages(district_id: str, mandal_id: str) -> list:
    # sType=U is the non-agriculture list (the agriculture one, R, differs slightly).
    params = {
        "districtcode": _require(district_id, _DISTRICT_RE, "district"),
        "mandalcode": _require(mandal_id, _CODE_RE, "mandal"),
        "sType": "U",
    }
    with _client() as client:
        resp = _get(client, "/UnitRateMV/getVillageListByDistCode", params)
    return _parse_pairs(resp.text)


def search_hyderabad_localities(division_id: str, query: str) -> list:
    division_id = _require(division_id, _CODE_RE, "division")
    query = _require(" ".join((query or "").split()), _LOCALITY_QUERY_RE, "locality text")
    return _fetch_localities(division_id, query.upper())


@lru_cache(maxsize=2048)
def _fetch_localities(division_id: str, query: str) -> list:
    # Unused ward/block slots are "$", the same placeholder the page's JS sends.
    codes = f"{HYDERABAD}~{query}~$~$~{division_id}"
    with _client() as client:
        resp = _get(client, "/UnitRateMV/getLocationDetails", {"codes": codes})
    return _parse_pairs(resp.text)


def fetch_rates(
    *,
    district_id: str,
    mandal_id: str = "",
    mandal: str = "",
    village_id: str = "",
    village: str = "",
    division_id: str = "",
    locality_id: str = "",
    locality: str = "",
) -> dict:
    district_id = _require(district_id, _DISTRICT_RE, "district")
    if district_id == HYDERABAD:
        fields = {
            "locName": _require_name(locality, "locality"),
            "rValue": "U",
            "tFlag": "L",
            "mndlName": "",
            "vlgName": "",
            "RateType": "U",
            "search_by": "L",
            "districtId": district_id,
            "mandalCode": "",
            "divCode": _require(division_id, _CODE_RE, "division"),
            "villageCode": "",
            "radio1": "l",
            "locality": _require(locality_id, _CODE_RE, "locality"),
        }
    else:
        fields = {
            "locName": "",
            "rValue": "U",
            "tFlag": "",
            "mndlName": _require_name(mandal, "mandal name"),
            "vlgName": _require_name(village, "village name"),
            "RateType": "U",
            "search_by": "L",
            "districtId": district_id,
            "mandalCode": _require(mandal_id, _CODE_RE, "mandal"),
            "divCode": "",
            "villageCode": _require(village_id, _CODE_RE, "village"),
            "locality": "",
        }

    key = tuple(fields.items())
    with _LOCKS[hash(key) % len(_LOCKS)]:
        return _rates(key, int(time.time() // _CACHE_SECONDS))


# shortcut: per-process cache in 6-hour buckets (rates change about once a year), so a
# repeat search skips the portal; move to Redis if we run more than one instance.
@lru_cache(maxsize=512)
def _rates(fields: tuple, _bucket: int) -> dict:
    fields = dict(fields)
    # The page's getJsonSubmit() serialises the form (encodestr is still empty at
    # that point) to JSON, base64-encodes it, and posts it alongside the fields.
    encoded = base64.b64encode(json.dumps({"encodestr": "", **fields}, separators=(",", ":")).encode()).decode()
    with _client() as client:
        resp = _post(client, "/UnitRateMV/unitRateMV", {"encodestr": encoded, **fields})
    return _parse_rates(resp.text)


_ERROR_PAGE_RE = re.compile(r"<h1>\s*Error Msg\s*</h1>")
_COLUMNS = ("ward_block", "locality", "land_rate_per_sq_yard", "effective_date")


def _cell_text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _parse_rates(html: str) -> dict:
    # The portal comments out columns it no longer shows (apartment rate,
    # classification); drop them so we return only what the official page shows.
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    if _ERROR_PAGE_RE.search(html):
        # The portal's generic rejection page for a combination it doesn't accept.
        raise PortalError(BAD_INPUT, "portal returned its Error Msg page")

    table = next((t for t in re.findall(r"<table.*?</table>", html, re.S) if "Land Value" in t), None)
    if table is None:
        # Neither the rates table nor the known error page — layout change or an
        # outage page. Don't guess; surface it as a portal problem.
        raise PortalError(PORTAL_DOWN, "unrecognized response shape from portal")

    rows = []
    for tr in re.findall(r"<tr.*?</tr>", table, re.S):
        cells = [_cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        # Data rows start with a serial number ("1."); the header row uses <th>.
        if len(cells) >= 5 and re.fullmatch(r"\d+\.?", cells[0]):
            rows.append(dict(zip(_COLUMNS, cells[1:5])))

    if not rows:
        raise PortalError(NO_RATES, "rates table had no data rows")

    return {"source": "igrs_market_value", "found": True, "rows": rows}
