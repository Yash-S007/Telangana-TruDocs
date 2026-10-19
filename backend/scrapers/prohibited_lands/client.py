"""Prohibited Properties under Section 22-A — registration.telangana.gov.in, Java + AngularJS.

Confirmed live (2026-10-15) by reading the page, its controller
(/resources/scripts/controllers/EditProhibitController.js), and replaying it:
- Public: no login, no captcha, no OTP, and no session cookie needed.
- District → Mandal → Village: POST MandalDetails.htm / VillageDetails.htm return
  JSON {"message": "success", "mandalDetails"/"villageDetails": [{"code", "name"}]}.
  Codes are the same as the Market Value search (Kokapet = 15_1 / 07 / 1516004).
- Hyderabad (16_1) has no mandals: mand_code is "00", its "villages" are the three
  divisions, an SRO office is required (getSRODetailsPDF.htm), and it has
  Non-Agriculture lists only.
- Fetch (prohibitionPublicList.htm) renders one button per 22-A(1) category under
  "Agriculture" and "Non-Agriculture". A button with empty arguments isn't
  available online (Waqf and Endowment, always). Each category is a PDF:
  checkPDFFile.htm, then viewProhibitedDataPDF.htm.
- "Court cases & Others" (prohibitedPropertyDetails_New.htm) is the survey-wise
  list. The page loads every row and filters in the browser, and so do we; one
  Hyderabad SRO is ~6,000 rows / 13 MB / ~30 s, hence the cache below.
- Each row links its order/notification PDF: ProhibitedPdfView.htm (id, property_type).
- Several columns are commented out in the HTML; we return only what the page shows.
"""
import json
import re
import threading
import time
from functools import lru_cache
from html import unescape

import httpx

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.scrapers.market_value.client import _throttle as market_value_throttle

BASE_URL = "https://registration.telangana.gov.in"
LANDING_PATH = "/openProhibitedProperties.htm"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HYDERABAD = "16_1"
HYDERABAD_MANDAL = "00"
KINDS = ("AGRI", "NONAGRI")

# What the official page says when a category's PDF isn't online.
NOT_PUBLISHED = "This list hasn't been published online yet. The department says it is under review."
# The portal answers a document request with an error page both when the document is
# gone and when its document service is down (seen live: every order failing for a
# while, then working again), so the honest message is "try later", not "no record".
DOC_UNAVAILABLE = "The department's website couldn't return this document right now. Please try again later."

# Same portal as market value (registration.telangana.gov.in), so both tools share one
# limit of 60 requests a minute.
_throttle = market_value_throttle

_CACHE_SECONDS = 6 * 3600
# Identical searches that arrive together wait for one portal fetch instead of each
# making their own. Striped locks keep this bounded; two different searches only
# share a lock 1 time in 32 (and then just wait their turn).
_LOCKS = [threading.Lock() for _ in range(32)]


def _lock(key: tuple) -> threading.Lock:
    return _LOCKS[hash(key) % len(_LOCKS)]

# Checked before anything reaches the portal.
_DISTRICT_RE = re.compile(r"\d{1,3}_\d{1,2}")
_CODE_RE = re.compile(r"\d{1,10}")
_SRO_RE = re.compile(r"\d{0,6}")
_FORMTYPE_RE = re.compile(r"\d")
_ORDER_ID_RE = re.compile(r"\d{6,25}")
_ORDER_FLAG_RE = re.compile(r"[A-Z]{1,4}")


def _client(timeout: float = 45.0) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT, "Referer": BASE_URL + LANDING_PATH},
        timeout=timeout,
        follow_redirects=True,
    )


def _request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        _throttle.wait()
        resp = client.request(method, path, **kwargs)
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


def _location(district_id: str, mandal_id: str, village_id: str, sro_code: str) -> tuple:
    district_id = _require(district_id, _DISTRICT_RE, "district")
    mandal_id = _require(mandal_id, _CODE_RE, "mandal")
    village_id = _require(village_id, _CODE_RE, "village")
    sro_code = _require(sro_code, _SRO_RE, "SRO")
    if district_id == HYDERABAD and (mandal_id != HYDERABAD_MANDAL or not sro_code):
        raise PortalError(BAD_INPUT, "Hyderabad needs mandal 00 and an SRO office")
    return district_id, mandal_id, village_id, sro_code


def _json(resp: httpx.Response, key: str) -> list:
    try:
        data = resp.json()
    except ValueError as exc:
        raise PortalError(PORTAL_DOWN, "portal returned non-JSON") from exc
    if data.get("message") != "success":
        # Seen live as a one-off "fail" that succeeds on retry: a portal hiccup, not "no record".
        raise PortalError(PORTAL_DOWN, f"portal message {data.get('message')!r}")
    return data.get(key) or []


def _text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


# ---------- location lists ----------


@lru_cache(maxsize=1)
def fetch_districts() -> list:
    """Server-rendered on the landing page; static for the life of the process."""
    with _client() as client:
        html = _request(client, "GET", LANDING_PATH).text
    m = re.search(r'<select[^>]*id="dist_code".*?</select>', html, re.S)
    options = re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)', m.group(0)) if m else []
    if not options:
        # Raise rather than return [] so lru_cache doesn't keep an empty list forever.
        raise PortalError(PORTAL_DOWN, "no district options on the page")
    return [{"value": v, "label": " ".join(t.split())} for v, t in options]


def fetch_mandals(district_id: str) -> list:
    district_id = _require(district_id, _DISTRICT_RE, "district")
    with _client() as client:
        resp = _request(client, "POST", "/MandalDetails.htm", data={"dist_code": district_id})
    return [{"value": m["code"], "label": " ".join(m["name"].split())} for m in _json(resp, "mandalDetails")]


def fetch_villages(district_id: str, mandal_id: str) -> list:
    params = {
        "dist_code": _require(district_id, _DISTRICT_RE, "district"),
        "mand_code": _require(mandal_id, _CODE_RE, "mandal"),
    }
    with _client() as client:
        resp = _request(client, "POST", "/VillageDetails.htm", params=params)
    return [{"value": v["code"], "label": " ".join(v["name"].split())} for v in _json(resp, "villageDetails")]


@lru_cache(maxsize=16)
def _fetch_sros(division_id: str) -> tuple:
    params = {"dist_code": HYDERABAD, "mand_code": HYDERABAD_MANDAL, "vill_code": division_id}
    with _client() as client:
        resp = _request(client, "GET", "/getSRODetailsPDF.htm", params=params)
    sros = tuple({"value": s["sro_code"], "label": " ".join(s["sro_name"].split())} for s in _json(resp, "SRODetails"))
    if not sros:
        raise PortalError(NOT_FOUND, "no SRO offices for this division")
    return sros


def fetch_hyderabad_sros(division_id: str) -> list:
    """SRO offices for one Hyderabad division (Hyderabad needs one picked)."""
    return list(_fetch_sros(_require(division_id, _CODE_RE, "division")))


# ---------- the 22-A(1) categories and their PDFs ----------

# Button label on the page → the category name we show.
_CATEGORY_RE = re.compile(r"getpdf1\(([^)]*)\)\"[^>]*>\s*<img[^>]*>\s*([^<]+?)\s*<")


def fetch_categories(*, district_id: str, mandal_id: str, village_id: str, sro_code: str = "") -> dict:
    loc = _location(district_id, mandal_id, village_id, sro_code)
    with _lock(("categories",) + loc):
        return _categories(*loc, int(time.time() // _CACHE_SECONDS))


# shortcut: per-process cache in 6-hour buckets (the category list changes rarely; the
# PDFs themselves are always fetched live); move to Redis for more than one instance.
@lru_cache(maxsize=512)
def _categories(district_id: str, mandal_id: str, village_id: str, sro_code: str, _bucket: int) -> dict:
    # The page's Fetch form is multipart; send the same.
    form = {"dist_code": district_id, "mand_code": mandal_id, "vill_code": village_id, "sro_code": sro_code}
    with _client() as client:
        resp = _request(client, "POST", "/prohibitionPublicList.htm", files={k: (None, v) for k, v in form.items()})
    return _parse_categories(resp.text)


def _parse_categories(html: str) -> dict:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    if "PROHIBITION LIST" not in html:
        raise PortalError(PORTAL_DOWN, "unrecognized response shape from portal")
    result = {}
    # Each column starts with <h4>Agriculture</h4> or <h4>Non-Agriculture</h4>.
    for heading, column in re.findall(r"<h4[^>]*>\s*([^<]+?)\s*</h4>(.*?)(?=<h4|$)", html, re.S):
        kind = {"agriculture": "AGRI", "non-agriculture": "NONAGRI"}.get(heading.strip().lower())
        if kind is None:
            continue
        categories = []
        for args, label in _CATEGORY_RE.findall(column):
            values = [a.strip().strip("'") for a in args.split(",")]
            available = len(values) == 6 and values[4] == kind and bool(_FORMTYPE_RE.fullmatch(values[5]))
            categories.append({
                "label": " ".join(label.split()).replace("22 A (1)", "22A(1)").replace(" (", "(").replace(")-", ") -"),
                "formtype": values[5] if available else "",
                "available": available,
            })
        if categories:
            result[kind] = categories
    if not result:
        raise PortalError(NOT_FOUND, "no prohibition categories on the page")
    return {"source": "igrs_prohibited_22a", "found": True, "categories": result}


def fetch_category_pdf(*, district_id: str, mandal_id: str, village_id: str, sro_code: str, kind: str, formtype: str) -> tuple:
    """The official PDF for one category. Returns (pdf_bytes, filename)."""
    district_id, mandal_id, village_id, sro_code = _location(district_id, mandal_id, village_id, sro_code)
    if kind not in KINDS:
        raise PortalError(BAD_INPUT, "invalid kind")
    formtype = _require(formtype, _FORMTYPE_RE, "category")
    with _client(timeout=120.0) as client:
        # The page asks checkPDFFile first; anything but "success" means not published.
        check = _request(client, "POST", "/checkPDFFile.htm", params={
            "dist_code": district_id, "mand_code": mandal_id, "vill_code": village_id,
            "prohib_type": kind, "formtype": formtype, "sroCode": sro_code,
        })
        if not _published(check.text):
            raise PortalError(NOT_PUBLISHED, "checkPDFFile did not return success")
        resp = _request(client, "POST", "/viewProhibitedDataPDF.htm", data={
            "dist_code": district_id, "mand_code": mandal_id, "vill_code": village_id,
            "prohib_type": kind, "formtype": formtype, "sro_code": sro_code,
        })
    return _require_pdf(resp.content), f"22A-{kind}-{formtype}-{village_id}{'-' + sro_code if sro_code else ''}.pdf"


def _published(check_json: str) -> bool:
    try:
        return json.loads(check_json).get("message") == "success"
    except (ValueError, AttributeError):
        return False


def _require_pdf(content: bytes) -> bytes:
    # The portal answers HTTP 200 with an HTML "Error Msg" page instead of a PDF.
    if content[:5] != b"%PDF-":
        raise PortalError(DOC_UNAVAILABLE, "portal returned a page instead of a PDF")
    return content


# ---------- the survey-wise list and its order PDFs ----------

_SURVEY_COLUMNS = (
    "sro", "ward_block", "door_no", "survey_no", "sub_survey_no", "rev_survey_no",
    "rev_sub_survey_no", "plot_no", "extent", "volume_page", "reason",
)


def fetch_survey_list(*, district_id: str, mandal_id: str, village_id: str, sro_code: str = "", kind: str) -> dict:
    district_id, mandal_id, village_id, sro_code = _location(district_id, mandal_id, village_id, sro_code)
    if kind not in KINDS:
        raise PortalError(BAD_INPUT, "invalid kind")
    key = (district_id, mandal_id, village_id, sro_code, kind)
    with _lock(("survey",) + key):
        rows = _survey_list(*key, int(time.time() // _CACHE_SECONDS))
    return {"kind": kind, "count": len(rows), "rows": rows}


# shortcut: per-process cache in 6-hour buckets, because the portal takes ~30 s for a
# Hyderabad SRO (~6,000 rows). Max 64 lists: most villages list a handful of rows and
# Hyderabad has only ~13 big ones. Move to Redis if we run more than one instance.
@lru_cache(maxsize=64)
def _survey_list(district_id: str, mandal_id: str, village_id: str, sro_code: str, kind: str, _bucket: int) -> list:
    with _client(timeout=150.0) as client:
        resp = _request(client, "POST", "/prohibitedPropertyDetails_New.htm", data={
            "dist_code": district_id, "sro_code": sro_code, "mand_code": mandal_id, "selectcriteria": "SNA",
            "vill_code": village_id, "distName": "", "mandalName": "", "villName": "", "prohib_type": kind,
        })
    return _parse_survey_list(resp.text)


def _parse_survey_list(html: str) -> list:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    m = re.search(r'<table[^>]*id="report".*?</table>', html, re.S)
    if m is None:
        if re.search(r"No Data Found|Error Msg", html):
            return []
        raise PortalError(PORTAL_DOWN, "unrecognized response shape from portal")
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", m.group(0), re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) < 12:
            continue  # header rows use <th>
        row = dict(zip(_SURVEY_COLUMNS, (_text(c) for c in cells[:11])))
        # Volume / page and order no / date are stacked in one cell, split by <hr/>.
        row["volume_page"] = " / ".join(_text(p) for p in re.split(r"<hr\s*/?>", cells[9]) if _text(p))
        order = re.split(r"<hr\s*/?>", cells[11])
        link = re.search(r"getFileView\('(\d+)'\s*,\s*'([A-Z]+)'\)", cells[11])
        row["order_no"] = _text(order[0])
        row["order_date"] = _text(order[1]) if len(order) > 1 else ""
        row["order_id"], row["order_flag"] = link.groups() if link else ("", "")
        rows.append(row)
    return rows


def fetch_order_pdf(order_id: str, flag: str) -> tuple:
    """The order/notification PDF a survey-list row points at. Returns (pdf_bytes, filename)."""
    order_id = _require(order_id, _ORDER_ID_RE, "order id")
    flag = _require(flag, _ORDER_FLAG_RE, "order type")
    with _client(timeout=120.0) as client:
        # prohib_type is a fixed "N" in the page's own form, on both lists.
        resp = _request(client, "POST", "/ProhibitedPdfView.htm", data={"property_type": flag, "id": order_id, "prohib_type": "N"})
    return _require_pdf(resp.content), f"22A-order-{order_id}.pdf"
