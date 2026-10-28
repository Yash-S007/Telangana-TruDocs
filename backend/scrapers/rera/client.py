"""RERA Certificate — Telangana RERA's public project search (rerait.telangana.gov.in).

No login or OTP. The search form has an image captcha (clean italic capitals on a dotted
background) that ddddocr reads, once uppercased, right first time in every sample; a wrong
guess comes back as the alert "Captcha is not valid." and we retry. Each result row's
certificate buttons carry a `data-qstr` token (base64 of ProjectID/UserID/AppID…). The
portal's own viewer posts that token to /SearchList/Show*CertificateIframe, which answers
with an iframe pointing at the PDF; neither step needs the search session.

The HTTPS server sends only its own certificate, not the "emSign SSL CA - G1" intermediate.
Browsers fetch that themselves; Python doesn't. We ship that public intermediate (checked:
signed by emSign Root CA - G1, which certifi trusts) rather than switching verification off.
"""
import base64
import binascii
import json
import re
import ssl
import threading
import time
from functools import lru_cache
from html import unescape
from pathlib import Path

import certifi
import httpx

from backend.core import pdf
from backend.core.captcha import solve as solve_captcha
from backend.core.errors import BAD_INPUT, CAPTCHA_FAILED, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter

BASE_URL = "https://rerait.telangana.gov.in"
SEARCH_PATH = "/SearchList/Search"
CAPTCHA_PATH = "/SearchList/SearchCaptcha"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PAGE_SIZE = 50  # 50 rows take a few seconds; "HOMES" alone matches 489 projects (19s for all of them)
CAPTCHA_ATTEMPTS = 5

# The portal's three certificate buttons, by the JS function each one calls.
KINDS = {
    "registration": "/SearchList/ShowCertificateIframe",
    "extension": "/SearchList/ShowExtensionCertificateIframe",
    "special-extension": "/SearchList/ShowWarExtensionCertificateIframe",
}
_BUTTON_KIND = {"showFile": "registration", "showExtensionFile": "extension", "showWarExtensionFile": "special-extension"}
_KIND_NAMES = {"extension": "Extension certificate", "special-extension": "4-month extension"}  # as the page names them

_SSL = ssl.create_default_context(cafile=certifi.where())
_SSL.load_verify_locations(cafile=str(Path(__file__).with_name("emsign_ssl_ca_g1.pem")))

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal

_CACHE_SECONDS = 6 * 3600
# Identical requests that arrive together wait for one portal fetch instead of each making
# their own (striped locks, as in the market value client). RERA records are public.
_LOCKS = [threading.Lock() for _ in range(32)]

# Checked before anything reaches the portal: the portal's own rule for names
# ([a-zA-Z0-9_ .&'-]) and field lengths, plus a 3-character minimum so one letter can't
# make it list thousands of projects.
_NAME_RE = re.compile(r"[A-Za-z0-9_ .&'-]{3,100}")
_REG_NO_RE = re.compile(r"[A-Za-z0-9]{4,15}")
_PROJECT_RE = re.compile(r"[A-Za-z0-9 .&'(),/@#:+_-]{1,100}")  # a project's name as the search lists it
NAME_CHARS = "Names can have English letters, digits, spaces and . & ' - _ only, at least 3 characters."
REG_NO_FORMAT = "A RERA registration number looks like P02400001224."
_TOKEN_RE = re.compile(
    r"ProjectID=(\d{1,10})&Division=\d{1,4}&UserID=\d{1,10}&RoleID=\d{1,4}&AppID=\d{1,10}"
    r"&Action=SEARCH&CharacterD=\d{1,4}&ExtAppID=\d{0,10}"
)
_FILE_SRC_RE = re.compile(r'src="(/SearchList/GetShow\w*CertificateFileContent[/?][A-Za-z0-9+/=%_?&.-]+)"')


def _client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout,
                        follow_redirects=True, verify=_SSL)


def _send(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        _throttle.wait()
        resp = client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PortalError(PORTAL_DOWN, str(exc)) from exc


def _clean(value: str, max_len: int) -> str:
    value = " ".join((value or "").split())
    if value and (len(value) > max_len or not _NAME_RE.fullmatch(value)):
        raise PortalError(NAME_CHARS, "unexpected characters or length in a name")
    return value


def _token_project_id(token: str) -> str:
    """The certificate token must be exactly what the portal hands out; anything else is refused."""
    try:
        decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise PortalError(BAD_INPUT, "invalid certificate token")
    m = _TOKEN_RE.fullmatch(decoded)
    if not m:
        raise PortalError(BAD_INPUT, "invalid certificate token")
    return m.group(1)


def _cell_text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _parse_results(html: str) -> dict:
    table = re.search(r"<table[^>]*>(.*?)</table>", html, re.S)
    if not table:
        if 'for="No_Records_Found"' in html:
            raise PortalError(NOT_FOUND, "no RERA project matches")
        raise PortalError(PORTAL_DOWN, "results page without a table")
    heads = [_cell_text(h).lower() for h in re.findall(r"<th[^>]*>(.*?)</th>", table.group(1), re.S)]
    col = {name: heads.index(name) for name in ("project name", "promoter name", "view details", "last modified date") if name in heads}
    if len(col) < 4:
        raise PortalError(PORTAL_DOWN, f"unexpected result columns {heads}")
    projects = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1), re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < len(heads):
            continue
        details = re.search(r"""href=["'](/PrintPreview/PrintPreview\?q=[^"']+)["']""", cells[col["view details"]])
        certificates = [
            {"kind": _BUTTON_KIND[fn], "token": token}
            for token, fn in re.findall(r"""data-qstr=['"]([A-Za-z0-9+/=]+)['"]\s+onclick="return (\w+)\(this\);\"""", row)
            if fn in _BUTTON_KIND
        ]
        projects.append({
            "project": _cell_text(cells[col["project name"]]),
            "promoter": _cell_text(cells[col["promoter name"]]),
            "last_modified": _cell_text(cells[col["last modified date"]]).split(" ")[0],
            "details_url": BASE_URL + unescape(details.group(1)) if details else "",
            "certificates": certificates,
        })
    if not projects:
        raise PortalError(NOT_FOUND, "no RERA project matches")
    total = re.search(r'id="TotalRecords"[^>]*value="(\d+)"', html)
    return {"total": int(total.group(1)) if total else len(projects), "shown": len(projects), "projects": projects}


def search_projects(project_name: str = "", promoter_name: str = "", registration_no: str = "") -> dict:
    fields = {
        "Project": _clean(project_name, 100),
        "Promoter": _clean(promoter_name, 50),
        "CertiNo": (registration_no or "").strip().upper(),
    }
    if fields["CertiNo"] and not _REG_NO_RE.fullmatch(fields["CertiNo"]):
        raise PortalError(REG_NO_FORMAT, "registration number is not 4-15 letters/digits")
    if not any(fields.values()):
        raise PortalError(BAD_INPUT, "enter a project name, promoter name or registration number")
    key = tuple(fields.items())
    with _LOCKS[hash(key) % len(_LOCKS)]:
        return _search(key, int(time.time() // _CACHE_SECONDS))


# shortcut: per-process cache in 6-hour buckets (registrations change slowly), so a repeat
# search skips the portal and its captcha; move to Redis if we run more than one instance.
@lru_cache(maxsize=512)
def _search(fields: tuple, _bucket: int) -> dict:
    form_fields = {
        "Type": "Promoter", "ID": "0", "pageTraverse": "1", "PageSize": str(PAGE_SIZE), "AgentName": "",
        "District": "", "Taluka": "", "Village": "", "CompletionDate_From": "", "CompletionDate_To": "",
        "PType": "", "PlotBearing": "", "Command": "Search", **dict(fields),
    }
    with _client() as client:
        page = _send(client, "GET", SEARCH_PATH).text
        for _ in range(CAPTCHA_ATTEMPTS):
            token = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', page)
            if not token:
                raise PortalError(PORTAL_DOWN, "search page without its form token")
            captcha = solve_captcha(_send(client, "GET", CAPTCHA_PATH).content).upper()
            page = _send(client, "POST", SEARCH_PATH, data={
                **form_fields, "__RequestVerificationToken": token.group(1), "Captcha": captcha,
            }).text
            if "Captcha is not valid" not in page:
                return _parse_results(page)
    raise PortalError(CAPTCHA_FAILED, "captcha retries exhausted")


def fetch_certificate(kind: str, token: str, project: str = "") -> tuple:
    """(pdf bytes, filename) for one of a project's certificates. `project` is its name as the
    search listed it, only for the file name (and the front page, which a signed one doesn't get)."""
    if kind not in KINDS:
        raise PortalError(BAD_INPUT, "unknown certificate kind")
    project_id = _token_project_id(token)
    with _LOCKS[hash((kind, token)) % len(_LOCKS)]:
        content = _certificate(kind, token, int(time.time() // _CACHE_SECONDS))
    project = " ".join((project or "").split())
    return pdf.document(content, "RERA Certificate", project if _PROJECT_RE.fullmatch(project) else f"Project ID {project_id}",
                        _KIND_NAMES.get(kind))


# shortcut: keeps the last 16 certificates (~0.5-0.9 MB each) for 6 hours; size it up or
# move it to disk if many people open the same certificates.
@lru_cache(maxsize=16)
def _certificate(kind: str, token: str, _bucket: int) -> bytes:
    with _client(timeout=90.0) as client:
        viewer = _send(client, "POST", KINDS[kind], content=json.dumps({"ID": token}),
                       headers={"Content-Type": "application/json"}).text
        src = _FILE_SRC_RE.search(viewer)  # only ever follow the portal's own certificate-file path
        if not src:
            raise PortalError(NOT_FOUND, "the portal has no certificate file for this project")
        file = _send(client, "GET", unescape(src.group(1))).content
    if not file.startswith(b"%PDF"):
        raise PortalError(NOT_FOUND, "the portal's certificate file is not a PDF")
    return file
