"""Adangal Extract (Pahani) — ccla.telangana.gov.in, Java/Struts 1.x.

Confirmed live (2026-09-29) by reading the actual page source and JS:
- District/Division/Mandal/Village cascade is server-rendered for District,
  then AJAX (`landStatus.do?method=getDivisions|getMandals|getVillages`) for
  the rest.
- The "captcha" is not an image at all — the answer is rendered in plain text
  in a <span id="showCaptcha"> and duplicated into a hidden field
  (`hidden_captcha`). No OCR is needed: just read the value and echo it back
  as `captcha_input`. This was verified directly against the live page source,
  not assumed.
- The actual search is a plain HTML form POST (`document.forms['landStatus'].submit()`
  after setting the hidden `method` field), not an AJAX call — so submitting
  requires replaying that full form post, not calling a JSON endpoint.
"""
import re
from functools import lru_cache
from html import unescape

import httpx
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.hierarchy import adangal_village
from backend.core.rate_limit import RateLimiter

BASE_URL = "https://ccla.telangana.gov.in"
LANDING_PATH = "/landStatus.do"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_throttle = RateLimiter(min_interval_seconds=1.0)
_ID_RE = re.compile(r"[0-9]{1,10}")  # not \d: that also matches Telugu and other non-ASCII digits
# Survey and khata numbers: digits, English or Telugu letters, / and - (e.g. 123, 5A, 45/1/అ)
_NUMBER_RE = re.compile(r"[0-9A-Za-z\u0c00-\u0c7f/ -]{1,20}")
NUMBER_CHARS = "A survey or khata number has only digits, letters and /, like 123 or 5A."
OPTIONS = ("surveyNo", "khataNo", "pattadarNo")


def _client(timeout: float = 45.0) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    )


def _get(client: httpx.Client, path: str) -> httpx.Response:
    try:
        _throttle.wait()
        resp = client.get(path)
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


# Some of these endpoints render `<option value=32>` with NO quotes around the
# value (confirmed live on getDivisions/getMandals/getVillages) — the pattern
# below matches both quoted and unquoted attribute values.
_OPTION_RE = re.compile(r'<option[^>]*value=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))[^>]*>([^<]*)')


def _find_options(html: str) -> list:
    results = []
    for m in _OPTION_RE.finditer(html):
        value = m.group(1) or m.group(2) or m.group(3) or ""
        label = re.sub(r"\s+", " ", m.group(4)).strip()
        if value and value != "0":
            results.append({"value": value, "label": label})
    return results


def _options(html: str, select_name: str) -> list:
    m = re.search(rf'<select[^>]*name="{re.escape(select_name)}"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return []
    return _find_options(m.group(1))


# Districts/Divisions/Mandals/Villages are government administrative
# boundaries — static for the life of this process and shared across every
# user, so caching them means only the first-ever lookup pays the real
# round-trip cost to CCLA's server; every repeat (by anyone) is instant.
# This is the actual fix for the cascade feeling slow, not something tunable
# client-side.


@lru_cache(maxsize=1)
def fetch_districts() -> list:
    with _client() as client:
        html = _get(client, LANDING_PATH).text
    return _options(html, "userProperties(district_id)")


@lru_cache(maxsize=64)
def fetch_divisions(district_id: str) -> list:
    # Confirmed live: params travel as a query string, not a POST body — the
    # site's own JS builds `landStatus.do?method=getDivisions&district_id=...`.
    with _client() as client:
        _get(client, LANDING_PATH)  # seed session cookie
        resp = _post(client, f"{LANDING_PATH}?method=getDivisions&district_id={district_id}", {})
    return _parse_ajax_options(resp.text)


@lru_cache(maxsize=256)
def fetch_mandals(district_id: str, division_id: str) -> list:
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _post(
            client,
            f"{LANDING_PATH}?method=getMandals&district_id={district_id}&division_id={division_id}",
            {},
        )
    return _parse_ajax_options(resp.text)


@lru_cache(maxsize=4096)
def fetch_villages(district_id: str, mandal_id: str) -> list:
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _post(
            client,
            f"{LANDING_PATH}?method=getVillages&district_id={district_id}&mandal_id={mandal_id}",
            {},
        )
    return _parse_ajax_options(resp.text)


def _parse_ajax_options(text: str) -> list:
    # These endpoints return a raw <option> fragment, not a full page.
    return _find_options(text)


@lru_cache(maxsize=8192)
def fetch_survey_options(village_id: str, option: str = "surveyNo") -> list:
    """`option` is "surveyNo", "khataNo", or "pattadarNo" — matches the
    portal's own toggle. Confirmed live: this endpoint (the currently-active
    JS, not the older commented-out version still present in the page source)
    takes all three fields in the POST body, with no query string."""
    if not _ID_RE.fullmatch(village_id or "") or option not in OPTIONS:
        raise PortalError(BAD_INPUT, "village code is digits; option is surveyNo, khataNo or pattadarNo")
    with _client() as client:
        _get(client, LANDING_PATH)
        resp = _post(
            client,
            LANDING_PATH,
            {"method": "getOptions", "village_id": village_id, "optionval1": option},
        )
    if resp.text.strip() == "NODATA":
        return []
    return _parse_ajax_options(resp.text)


def fetch_adangal(
    *,
    district_id: str,
    division_id: str,
    mandal_id: str,
    village_id: str,
    survey_or_khata_value: str,
    option: str = "surveyNo",
) -> dict:
    if not all([district_id, division_id, mandal_id, village_id, survey_or_khata_value]):
        raise PortalError(BAD_INPUT, "district, division, mandal, village and survey/khata number are all required")
    if option not in ("surveyNo", "khataNo"):
        raise PortalError(BAD_INPUT, "option must be surveyNo or khataNo")
    if not all(_ID_RE.fullmatch(x) for x in (district_id, division_id, mandal_id, village_id)):
        raise PortalError(BAD_INPUT, "location codes are digits")
    survey_or_khata_value = survey_or_khata_value.strip()
    if not _NUMBER_RE.fullmatch(survey_or_khata_value):
        raise PortalError(NUMBER_CHARS, "unexpected characters in the survey/khata number")

    with _client() as client:
        _get(client, LANDING_PATH)  # seed JSESSIONID

        # Confirmed live: the captcha value embedded in the initial page load is
        # NOT what the server validates the final submit against — only an
        # explicit refreshCaptcha call actually sets the session-bound expected
        # value (the page-load one caused a server-side "mismatch" rejection in
        # testing). Always fetch a fresh one this way immediately before submit.
        refresh_resp = _post(
            client, f"{LANDING_PATH}?method=refreshCaptcha", {"captchaType": "ror"}
        )
        captcha_value = refresh_resp.text.strip()
        if not captcha_value:
            raise PortalError(PORTAL_DOWN, "could not obtain a fresh captcha value")

        # The real form action includes a jsessionid-bearing path
        # (`/landStatus.done;jsessionid=...`); httpx's cookie jar already
        # tracks JSESSIONID from the Set-Cookie header, so posting back to the
        # plain landStatus.do with that cookie attached is equivalent and
        # avoids depending on regex-extracting the exact rewritten URL.
        payload = {
            "method": "getLandDetails",
            "userProperties(district_id)": district_id,
            "userProperties(division_id)": division_id,
            "userProperties(mandal_id)": mandal_id,
            "userProperties(village_id)": village_id,
            "userProperties(option1)": option,
            "userProperties(khata_survey_pattadar)": survey_or_khata_value,
            "userProperties(h_option1)": option,
            "userProperties(h_khata_survey_pattadar)": survey_or_khata_value,
            "hidden_captcha": captcha_value,
            "userProperties(captcha_input)": captcha_value,
        }
        resp = _post(client, LANDING_PATH, payload)

    return _parse_result(resp.text)


_NOT_FOUND_RE = re.compile(r'<font[^>]*color:\s*red[^>]*>\s*(No [^<]*?Found)\s*</font>', re.I)


def _parse_result(html: str) -> dict:
    # IMPORTANT (found the hard way via a byte-diff against a fresh page load):
    # this page's static <script> block always contains the words "captcha"
    # and "invalid" (e.g. in "Invalid option selected") on EVERY render,
    # success or failure — an earlier version of this function treated that
    # combination as a captcha-mismatch signal and was wrong 100% of the time.
    # A real "no results for this survey/khata number" response instead
    # renders a specific message like "No RoR-1B Details Found" inside a
    # <font color="red"> tag in the results section (#rorDiv / #pahaniDiv) —
    # that is the actual, confirmed-live signal to key off.
    not_found_messages = _NOT_FOUND_RE.findall(html)

    # A genuine result renders a data table inside the results rows, not just
    # the page's own layout tables (nav/footer tables etc. always exist) — so
    # only count tables that appear inside the rorDiv/pahaniDiv result blocks.
    result_section = re.search(r'id="rorDiv".*?id="pahaniDiv".*?</tr>', html, re.S)
    section_html = result_section.group(0) if result_section else ""
    data_tables = re.findall(r"<table[^>]*>.*?</table>", section_html, re.S)

    if not_found_messages and not data_tables:
        raise PortalError(NOT_FOUND, f"portal reported: {'; '.join(not_found_messages)}")

    if not not_found_messages and not data_tables:
        # Neither a known "not found" message nor a data table was seen —
        # something unexpected happened (portal error page, layout change,
        # etc.). Don't guess; surface as a portal error rather than silently
        # claiming success or a specific known failure mode.
        raise PortalError(PORTAL_DOWN, "unrecognized response shape from portal")

    return {
        "source": "adangal_pahani",
        "found": bool(data_tables),
        "not_found_messages": not_found_messages,
        "raw_tables_html": data_tables[:3],
    }


# ---------- a Pahani as a PDF ----------
# It names its owners: each PDF is made from its own search and kept nowhere.
def fetch_adangal_pdf(**fields) -> tuple:
    """(pdf bytes, filename): the portal's Pahani tables as our PDF, landscape for their many columns."""
    data = fetch_adangal(**fields)  # checks the fields
    number = fields["survey_or_khata_value"].strip()
    kind = "Khata" if fields.get("option") == "khataNo" else "Survey"
    village = adangal_village(fields["village_id"].strip())
    name = lambda key: village[key].split("|")[0].strip()  # "Ankapoor | అంకాపూర్" → "Ankapoor"
    place = f" · {name('village')} village, {name('mandal')} mandal, {name('district')} district" if village else ""
    searched = f"{kind} No. {number}{place}"
    story = [pdf.para("Adangal (Pahani)", "title"), pdf.para(searched, "sub")]
    for html in data["raw_tables_html"]:
        rows = _table_rows(html)
        if rows:
            width = max(len(r) for r in rows)
            cells = [[pdf.para(c, "label" if i == 0 else "cell") for c in r + [""] * (width - len(r))]  # short rows padded
                     for i, r in enumerate(rows)]
            story += [Spacer(0, 5 * mm), pdf.cells(cells, [(landscape(A4)[0] - 2 * pdf.MARGIN) / width] * width, header=True)]
    content = pdf.build(story, title=f"Adangal (Pahani): {searched}", pagesize=landscape(A4),
                        note="For reference only: not a certified copy of the Pahani.",
                        source="CCLA Telangana land records (ccla.telangana.gov.in)")
    return content, pdf.filename("Adangal", name("village") if village else "", kind.lower(), number)


def _table_rows(html: str) -> list:
    """A portal table as rows of cell text. shortcut: merged cells (colspan/rowspan) are laid out
    as single cells, so a merged heading shifts its row; fix once the portal shows a real Pahani
    (it had none for any number tried, Oct 2026)."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [" ".join(unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)]
        if any(cells):
            rows.append(cells)
    return rows
