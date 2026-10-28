"""Pattadar Passbook (Land Details Search) — bhubharati.telangana.gov.in,
Java/Spring Boot ("Dharani" backend family).

Two real things found by reading this page's actual JS (confirmed against a
real captured browser session's request/response pair, not guessed):

1. District/Mandal/Village cascade uses plain GET endpoints that return raw
   <option> fragments — but Mandal/Village need query params, not a request
   body (`getMandalFromDivisionCitizenPortal?district=..`,
   `getVillageFromMandalCitizenPortal?mandalId=..`).

2. The final search (`getPublicDataInfo`) requires two fields —
   `searchData` (the survey number) and `captcha` (the solved captcha text)
   — to be AES-128-CBC encrypted client-side before being sent, using a
   HARDCODED key+IV found in plain sight in their own `js/aes.js`:
     key = base64("u/Gu5posvwDsXUnV5Zaq4g==")
     iv  = base64("5D9r9ZVzEYYgha93/aUK2w==")
   PKCS7 padding, UTF-8 plaintext, output is base64(ciphertext) (no salt/IV
   prepended). Verified byte-for-byte against a real captured
   plaintext/ciphertext pair from the live site before relying on this.
"""
import random
import re
from functools import lru_cache

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import base64
import threading
from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from backend.core import pdf
from backend.core.captcha import solve as solve_captcha
from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.hierarchy import pattadar_village
from backend.core.rate_limit import RateLimiter

BASE_URL = "https://bhubharati.telangana.gov.in"
LANDING_PATH = "/knowLandStatus"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal

# Single-flight: identical searches arriving together wait for one portal flow instead
# of each solving its own captcha and hammering the portal. Nothing is retained after
# the request finishes, so no personal result is cached at rest — only in-flight callers
# share the one result.
_inflight_lock = threading.Lock()
_inflight: dict = {}


class _Call:
    __slots__ = ("event", "result", "exc")

    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.exc = None


def _single_flight(key: tuple, work):
    with _inflight_lock:
        call = _inflight.get(key)
        leader = call is None
        if leader:
            call = _inflight[key] = _Call()
    if not leader:
        call.event.wait()
        if call.exc is not None:
            raise call.exc
        return call.result
    try:
        call.result = work()
        return call.result
    except BaseException as exc:
        call.exc = exc
        raise
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        call.event.set()


_AES_KEY = base64.b64decode("u/Gu5posvwDsXUnV5Zaq4g==")
_AES_IV = base64.b64decode("5D9r9ZVzEYYgha93/aUK2w==")


def _enc(plaintext: str) -> str:
    cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_IV)
    padded = pad(plaintext.encode("utf-8"), AES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode("ascii")


def _client(timeout: float = 45.0) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest", "Referer": BASE_URL + LANDING_PATH},
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


# Checked before anything reaches the portal. Values also travel as encoded params:
# pasting them into the URL let "507004&flag=x" rewrite the portal request.
_ID_RE = re.compile(r"[0-9]{1,10}")  # not \d: that also matches Telugu and other non-ASCII digits
# Survey numbers mix digits, "/" and Telugu letters plus vowel signs (e.g. "1/2అ",
# which a \w whitelist would reject), so block only characters that could change a
# request's meaning.
_SURVEY_BAD_RE = re.compile(r"[&#?=%<>\"'\\\x00-\x1f]")


def _check_id(value: str, what: str) -> str:
    value = (value or "").strip()
    if not _ID_RE.fullmatch(value):
        raise PortalError(BAD_INPUT, f"invalid {what}")
    return value


def _check_survey(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 40 or _SURVEY_BAD_RE.search(value):
        raise PortalError(BAD_INPUT, "invalid survey number")
    return value


_OPTION_RE = re.compile(r'<option[^>]*value=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))[^>]*>([^<]*)')


def _find_options(html: str) -> list:
    results = []
    for m in _OPTION_RE.finditer(html):
        value = m.group(1) or m.group(2) or m.group(3) or ""
        label = re.sub(r"\s+", " ", m.group(4)).strip()
        if value and value != "0":
            results.append({"value": value, "label": label})
    return results


def _options(html: str) -> list:
    """A list reply's options. A real empty list still carries "-- Select --"; a reply with no
    <option> at all (a maintenance or error page) raises, so lru_cache never keeps it as empty."""
    if "<option" not in html.lower():
        raise PortalError(PORTAL_DOWN, "no list in the portal's reply")
    return _find_options(html)


# Districts/Mandals/Villages are government administrative boundaries — they
# don't change while this process is running, and are shared across every
# user. Caching them turns "every dropdown click re-hits the government
# server" into "the first click anyone makes populates it for everyone after,
# instantly" — the real fix for the cascade feeling slow, since each live
# call is a full round-trip to a Java/Spring server on the other side of
# India. Survey/khata numbers are also cached per (village[, survey]) since
# those are likewise static once published, just far more numerous.


@lru_cache(maxsize=1)
def fetch_districts() -> list:
    with _client() as client:
        html = _get(client, LANDING_PATH).text
    m = re.search(r'id="districtID"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        raise PortalError(PORTAL_DOWN, "no district list on the page")
    return _find_options(m.group(1))


@lru_cache(maxsize=64)
def fetch_mandals(district_id: str) -> list:
    district_id = _check_id(district_id, "district")
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _get(client, "/getMandalFromDivisionCitizenPortal", {"district": district_id})
    return _options(resp.text)


@lru_cache(maxsize=1024)
def fetch_villages(mandal_id: str) -> list:
    mandal_id = _check_id(mandal_id, "mandal")
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _get(client, "/getVillageFromMandalCitizenPortal", {"mandalId": mandal_id})
    return _options(resp.text)


@lru_cache(maxsize=4096)
def fetch_survey_options(village_id: str) -> list:
    village_id = _check_id(village_id, "village")
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _get(client, "/getSurveyCitizen", {"villId": village_id, "flag": "survey"})
    return _options(resp.text)


@lru_cache(maxsize=8192)
def fetch_khata_options(village_id: str, survey_no: str) -> list:
    village_id = _check_id(village_id, "village")
    survey_no = _check_survey(survey_no)
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _get(client, "/getKhataNoCitizen", {"villId": village_id, "flag": "khatanos", "surveyNo": survey_no})
    return _options(resp.text)


# Fixed token the page sends for the "passbook number + Aadhaar last 4" mode
# (ppbType1 in the page JS, already base64 so it is sent as-is, not re-encrypted).
_PPB_TYPE_AADHAAR = "eHdKAPzoX7n3faJvdKTkIA=="


def _search_with_captcha(client: httpx.Client, build_request, max_attempts: int) -> dict:
    """Run the portal's search, solving its captcha with ddddocr and retrying.

    `build_request(encrypted_captcha)` returns (url_params, body) for getPublicDataInfo.
    Survey and passbook searches differ only there; everything else is shared.

    Confirmed live: this portal's grid/mesh-noise captcha measures ~50% single-shot
    accuracy with ddddocr (verified against 6 real samples) — a harder OCR class than
    Adangal's plaintext "captcha". 8 attempts at ~50% each is ~99.6% odds of one
    success, cheaper than a heavier OCR tier.
    """
    last_detail = ""
    for _ in range(max_attempts):
        rand = random.random()
        captcha_resp = _get(client, f"/captchaforViewRorandPahani?rand_number={rand}")
        # Confirmed live: every captcha sample observed is uppercase-only (digits +
        # uppercase letters); ddddocr's general model sometimes returns the right
        # letter in the wrong case (e.g. "1bEK9" for "1BEK9"), which silently fails
        # the server match. Force uppercase rather than trust the raw OCR case.
        captcha_text = solve_captcha(captcha_resp.content).upper()
        if not captcha_text:
            last_detail = "ocr produced empty result"
            continue

        encrypted_captcha = _enc(captcha_text)

        # Confirmed from a captured session: the site calls
        # /checkcaptchaforViewRorandPahani with the encrypted captcha as a query
        # param (empty body) before the main submit — this "commits" the captcha to
        # the session; skipping it makes getPublicDataInfo return the generic error
        # page even for a correct captcha. A failure here (network/unexpected) falls
        # through to the submit, since the pre-check doesn't return the land data.
        try:
            _throttle.wait()
            check_resp = client.post(
                "/checkcaptchaforViewRorandPahani",
                params={"captcha": encrypted_captcha},
                content=b"",
            )
            check_resp.raise_for_status()
            check_body = check_resp.text.strip().lower()
            if check_body in ("false", "0", "fail", "invalid"):
                last_detail = f"captcha pre-check rejected captcha guess {captcha_text!r}"
                continue
        except (httpx.TimeoutException, httpx.HTTPError):
            pass  # if pre-check is unavailable, still attempt the main submit

        url_params, data = build_request(encrypted_captcha)
        try:
            _throttle.wait()
            resp = client.post("/getPublicDataInfo", params=url_params, data=data)
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise PortalError(PORTAL_DOWN, str(exc)) from exc

        lower = resp.text.lower()
        # Confirmed live: a wrong captcha does NOT give a specific "captcha
        # incorrect" message — it gives this same generic Spring/JSP error page
        # ("Something went wrong..."). Since the other fields are already valid,
        # treat it as a captcha-retry signal, not a hard failure.
        if "something went wrong" in lower or 'id="txtlogout"' in lower:
            last_detail = f"portal error page (likely wrong captcha guess {captcha_text!r})"
            continue

        return _parse_result(resp.text)

    raise PortalError(CAPTCHA_FAILED, last_detail or "captcha retries exhausted")


def fetch_pattadar_by_survey(
    *, district_id: str, mandal_id: str, village_id: str, survey_no: str, khata_id: str, max_attempts: int = 8
) -> dict:
    district_id = _check_id(district_id, "district")
    mandal_id = _check_id(mandal_id, "mandal")
    village_id = _check_id(village_id, "village")
    khata_id = _check_id(khata_id, "khata")
    survey_no = _check_survey(survey_no)

    def build_request(captcha: str):
        # Confirmed from a captured session: district and mandal travel in the URL
        # query string; the body carries villageId/searchData/captcha etc.
        return (
            {"district": district_id, "mandal": mandal_id, "divi": ""},
            {
                "villageId": village_id,
                "flagToSearch": "surveynumber",
                "searchData": _enc(survey_no),
                "flagval": "district",
                "khataNoIdselect": khata_id,
                "ReqType": "Citizen",
                "captcha": captcha,
            },
        )

    def work():
        with _client() as client:
            _get(client, LANDING_PATH)  # seed JSESSIONID/setAuth cookies
            return _search_with_captcha(client, build_request, max_attempts)

    return _single_flight(("survey", district_id, mandal_id, village_id, survey_no, khata_id), work)


def fetch_pattadar_by_passbook(
    *, passbook_no: str, aadhaar_last4: str, flagval: str = "ppb", max_attempts: int = 8
) -> dict:
    """Search by passbook (PPB) number + the last 4 digits of the owner's Aadhaar.

    The page encrypts the Aadhaar digits (AES, same key as everything else) and sends
    the real values in the URL query string, like the survey search. We never log
    either value (SKILL.md rule 3)."""
    passbook_no = (passbook_no or "").strip()
    aadhaar_last4 = (aadhaar_last4 or "").strip()
    if not passbook_no or not aadhaar_last4:
        raise PortalError(BAD_INPUT, "passbook number and the last 4 Aadhaar digits are both required")
    if not re.fullmatch(r"[A-Za-z0-9]{1,12}", passbook_no):
        raise PortalError(BAD_INPUT, "passbook number looks invalid")
    if not re.fullmatch(r"[0-9]{4}", aadhaar_last4):
        raise PortalError(BAD_INPUT, "enter exactly the last 4 digits of the Aadhaar number")

    def build_request(captcha: str):
        return (
            {
                "villageId": "",
                "adhrfour": _enc(aadhaar_last4),
                "ppbno": passbook_no,
                "flagval": flagval,
                "ppbType": _PPB_TYPE_AADHAAR,
                "ReqType": "Citizen",
                "captcha": captcha,
            },
            {
                "villageId": "",
                "adhrfour": "",
                "ppbno": passbook_no,
                "flagval": flagval,
                "ReqType": "Citizen",
                "captcha": captcha,
            },
        )

    def work():
        with _client() as client:
            _get(client, LANDING_PATH)
            result = _search_with_captcha(client, build_request, max_attempts)
        if not result["found"]:
            # A non-existent passbook/Aadhaar pair returns an empty reply (no fields),
            # not the survey search's "no record" text — surface it the same way.
            raise PortalError(NOT_FOUND, "no record for that passbook number and Aadhaar digits")
        return result

    return _single_flight(("passbook", passbook_no, aadhaar_last4), work)


_FIELD_RE = re.compile(r"<strong>([^<]+)</strong>\s*<br>\s*([^<]*)", re.S)
_SECTION_RE = re.compile(r'<h4 class="heading-details">([^<]+)</h4>')


def _parse_result(html: str) -> dict:
    lower = html.lower()
    if "no record" in lower or "no data found" in lower:
        raise PortalError(NOT_FOUND, "portal reported no record")
    if "something went wrong" in lower:
        raise PortalError(PORTAL_DOWN, "portal returned its generic error page")

    fields = {
        label.strip(): re.sub(r"\s+", " ", value).strip()
        for label, value in _FIELD_RE.findall(html)
    }
    sections = _SECTION_RE.findall(html)

    return {
        "source": "pattadar_passbook",
        "sections": sections,
        "raw_fields": fields,
        "found": bool(fields),
    }


# ---------- a record as a PDF ----------
# Someone's land record: each PDF is made from its own search and kept nowhere.
def fetch_survey_pdf(**fields) -> tuple:
    """(pdf bytes, filename) for a survey + khata search."""
    record = fetch_pattadar_by_survey(**fields)  # checks the fields
    survey = fields["survey_no"].strip()
    village = pattadar_village(fields["village_id"].strip())
    name = lambda key: village[key].split("|")[0].strip()  # "Ankapoor|అంకాపూర్" → "Ankapoor"
    place = f" · {name('village')} village, {name('mandal')} mandal, {name('district')} district" if village else ""
    return pdf.document(_record_pdf(record, f"Survey No. {survey}{place}"), "Land Details Search",
                        name("village") if village else "", f"Survey No. {survey}")


def fetch_passbook_pdf(passbook_no: str, aadhaar_last4: str) -> tuple:
    """(pdf bytes, filename) for a passbook search. The Aadhaar digits are not printed."""
    record = fetch_pattadar_by_passbook(passbook_no=passbook_no, aadhaar_last4=aadhaar_last4)
    number = passbook_no.strip()
    return pdf.document(_record_pdf(record, f"Passbook No. {number}"), "Land Details Search", f"Passbook No. {number}")


def _record_pdf(record: dict, searched: str) -> bytes:
    if not record["found"]:
        raise PortalError(NOT_FOUND, "portal reply had no fields")
    return pdf.build([pdf.para("Land Details (Bhu Bharati)", "title"), pdf.para(searched, "sub"), Spacer(0, 5 * mm),
                      pdf.fields(record["raw_fields"].items())],
                     title=f"Land details: {searched}", note="For reference only: not a certified copy of the land record.",
                     source="Bhu Bharati, the Telangana land records portal (bhubharati.telangana.gov.in)")
