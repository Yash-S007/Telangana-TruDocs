"""Hydra FTL Map — a lake's official Full Tank Level (FTL) and buffer-zone maps from HMDA's lakes
portal (lakes.hmda.gov.in), plus the government's survey of water bodies in the lake's village.

HMDA portal: no login, captcha or OTP. Its home page is one 4 MB table of every lake HMDA has
notified (~3,000 in 7 districts), so it is read once and kept for 6 hours. Each lake's FTL map,
cadastral map and survey-number statement are static PDFs, but their file names follow no pattern
(an "_" after the ID or not, "/" turned into "-", even typos), so a PDF is found the way the page
finds it: a postback of the row's button, answered with a redirect to the file.

The water-body survey (TGRAC's Tank Information System, 2011 and 2023) uses neither HMDA's lake
IDs nor, mostly, names, so it can't say which of its water bodies is this lake; it is matched by
village only and shown as the village's water bodies.
"""
import html
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

import httpx

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter
from backend.core.single_flight import single_flight

BASE_URL = "https://lakes.hmda.gov.in/"
FILES_URL = BASE_URL + "hmdalake/"  # where the postbacks send you: static PDFs
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
WATER_BODIES_FILE = Path(__file__).resolve().parents[2] / "data" / "hydra_water_bodies.json"

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal
_CACHE_SECONDS = 6 * 3600  # new notifications are added a few times a year
SEARCH_SHOWN = 50

# kind → (the row's button, the file name's ending, label), in the order the preview offers them.
DOCUMENTS = {
    "ftl": ("btn_pros", "FTL", "FTL and buffer zone map"),
    "cadastral": ("btn_plan", "CADASTRAL", "FTL on the village survey map (cadastral)"),
    "survey": ("btn_bufferzone", "SyNo", "Survey numbers in the FTL and buffer zone"),
}
_PDF_LINK_RE = re.compile(r"https?://lakes\.hmda\.gov\.in/hmdalake/([^/?#]+)\.pdf", re.I)  # http: the portal's own redirects
_TEXT_RE = re.compile(r"[A-Za-z0-9 /&().,'`_\"-]{1,80}")


def _client(timeout: float = 90.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=httpx.HTTPTransport(retries=1),
                        headers={"User-Agent": USER_AGENT, "Referer": BASE_URL})


def _send(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    try:
        _throttle.wait()
        return client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PortalError(PORTAL_DOWN, str(exc)) from exc


def _cell(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _parse(page: str) -> dict:
    """The page's form state (sent back with every postback) and its lakes, by key."""
    form = {k: html.unescape(v) for k, v in re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"', page)}
    grid = page.find('id="gv_showlakes"')
    if "__VIEWSTATE" not in form or grid < 0:
        raise PortalError(PORTAL_DOWN, "lakes page without its table")
    lakes = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page[grid:], re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ctl = re.search(r"gv_showlakes\$(ctl\d+)\$", row)
        if len(tds) < 11 or not ctl:
            continue
        _, district, mandal, village, name, lake_id, prelim, final = (_cell(c) for c in tds[:8])
        if not lake_id or not name or district.startswith("--"):  # the table has a few empty rows
            continue
        lake = {"key": f"{lake_id}|{name}", "id": lake_id, "name": name, "district": district, "mandal": mandal,
                "village": village, "preliminary": prelim, "final": final, "ctl": ctl.group(1),
                "documents": [k for k, (button, _, _) in DOCUMENTS.items() if f"${button}'" in html.unescape(row)]}
        # A few lakes are listed twice; keep the fuller row (one may lack the final notification).
        old = lakes.get(lake["key"])
        if old is None or (len(lake["documents"]), bool(final)) > (len(old["documents"]), bool(old["final"])):
            lakes[lake["key"]] = lake
    if len(lakes) < 100:
        raise PortalError(PORTAL_DOWN, f"only {len(lakes)} lakes on the page")
    return {"form": form, "lakes": lakes}


def _page() -> dict:
    bucket = int(time.time() // _CACHE_SECONDS)
    return single_flight(("hydra-page", bucket), lambda: _load_page(bucket))


# shortcut: per-process cache of the whole table (~2 MB once parsed); move to Redis if we run more
# than one instance.
@lru_cache(maxsize=1)
def _load_page(_bucket: int) -> dict:
    with _client() as client:
        resp = _send(client, "GET", BASE_URL)
    if resp.status_code != 200:
        raise PortalError(PORTAL_DOWN, f"lakes page HTTP {resp.status_code}")
    return _parse(resp.text)


def _public(lake: dict) -> dict:
    return {k: lake[k] for k in ("key", "id", "name", "district", "mandal", "village", "preliminary", "final")}


def fetch_places() -> list:
    """District → mandal → village, for the villages that have notified lakes."""
    tree = {}
    for lake in _page()["lakes"].values():
        tree.setdefault(lake["district"], {}).setdefault(lake["mandal"], set()).add(lake["village"])
    return [{"district": d, "mandals": [{"mandal": m, "villages": sorted(vs)} for m, vs in sorted(ms.items())]}
            for d, ms in sorted(tree.items())]


def _check(value: str) -> str:
    value = (value or "").strip()
    if not _TEXT_RE.fullmatch(value):
        raise PortalError(BAD_INPUT, "unexpected characters")
    return value


def find_lakes(district: str = "", mandal: str = "", village: str = "", q: str = "") -> dict:
    """The lakes in one village, or those whose name or lake ID contains `q`."""
    lakes = _page()["lakes"].values()
    if q:
        q = _check(q)
        if len(q) < 2:
            raise PortalError(BAD_INPUT, "type at least 2 letters of the lake's name or ID")
        needle = q.lower()
        found = [l for l in lakes if needle in l["name"].lower() or needle in l["id"].lower()]
    else:
        place = (_check(district), _check(mandal), _check(village))
        found = [l for l in lakes if (l["district"], l["mandal"], l["village"]) == place]
    if not found:
        raise PortalError(NOT_FOUND, "no notified lake matches")
    found.sort(key=lambda l: (l["district"], l["mandal"], l["village"], l["name"].lower()))
    return {"total": len(found), "shown": min(len(found), SEARCH_SHOWN), "lakes": [_public(l) for l in found[:SEARCH_SHOWN]]}


def _lake(key: str) -> dict:
    lake = _page()["lakes"].get((key or "").strip())  # only ever a lookup in the table we read
    if lake is None:
        raise PortalError(NOT_FOUND, "no lake with this key")
    return lake


def fetch_lake(key: str) -> dict:
    """A lake's notification details, its official maps, and the survey of its village's water bodies."""
    lake = _lake(key)
    return {"source": "hmda_lakes", "found": True, **_public(lake),
            "documents": [{"kind": k, "label": DOCUMENTS[k][2]} for k in lake["documents"]],
            "water_bodies": water_bodies(lake["district"], lake["mandal"], lake["village"])}


def fetch_document(key: str, kind: str) -> tuple:
    """(pdf bytes, filename): one of the lake's official PDFs."""
    if kind not in DOCUMENTS:
        raise PortalError(BAD_INPUT, "unknown document")
    lake = _lake(key)
    if kind not in lake["documents"]:
        raise PortalError(NOT_FOUND, "HMDA has no such document for this lake")
    bucket = int(time.time() // _CACHE_SECONDS)
    pdf = single_flight(("hydra-doc", lake["key"], kind, bucket), lambda: _document(lake["key"], kind, bucket))
    safe = re.sub(r"[^A-Za-z0-9]+", "-", f"{lake['name']} {lake['id']}").strip("-")
    return pdf, f"HMDA-Lake-{safe}-{DOCUMENTS[kind][1]}.pdf"


def _for_lake(filename: str, lake: dict) -> bool:
    """Is this file this lake's: its ID ("1025_…", not "10251_…") or its name in the file name?
    Guards against a stale table pointing at another row. The kind isn't checked: the button
    decides it, and HMDA writes it several ways ("…_FTL", "…_FTL_final", "…_cadastral_final")."""
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    name, lake_id = squash(filename), squash(lake["id"])
    return squash(lake["name"]) in name or (name.startswith(lake_id) and not name[len(lake_id):][:1].isdigit())


# shortcut: keeps the last 16 PDFs (0.1-4 MB each) for 6 hours; move to disk if many people
# open the same lakes.
@lru_cache(maxsize=16)
def _document(key: str, kind: str, _bucket: int) -> bytes:
    for attempt in range(2):
        page = _page()
        lake = page["lakes"].get(key)
        if lake is None:
            raise PortalError(NOT_FOUND, "the lake is no longer on HMDA's list")
        form = {**page["form"], "__EVENTTARGET": f"gv_showlakes${lake['ctl']}${DOCUMENTS[kind][0]}", "__EVENTARGUMENT": "",
                "ddl_district": "0", "ddl_notifacation": "0", "txt_lakeid": "", "txt_lakename": ""}
        with _client() as client:
            resp = _send(client, "POST", BASE_URL, data=form)
            link = _PDF_LINK_RE.fullmatch(resp.headers.get("location", "")) if resp.status_code == 302 else None
            if link and _for_lake(unquote(link[1]), lake):
                pdf = _send(client, "GET", FILES_URL + link[1] + ".pdf")
                if pdf.status_code == 404:
                    raise PortalError(NOT_FOUND, "HMDA lists this PDF but its file is missing")
                if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
                    raise PortalError(PORTAL_DOWN, f"PDF HTTP {pdf.status_code}")
                return pdf.content
        # The saved page may be out of date (HMDA added lakes): read it again once and retry.
        _load_page.cache_clear()
    raise PortalError(PORTAL_DOWN, f"postback gave HTTP {resp.status_code}, no PDF link")


# ---------- the government's water-body survey, by village ----------

def _squash(name: str) -> str:
    """Spellings the two sources disagree on: Thimmapalli / Thimmapally, Peerzadiguda / Peerzaadiguda."""
    s = re.sub(r"[^a-z]", "", (name or "").lower())
    for a, b in (("palli", "pally"), ("palle", "pally"), ("pali", "pally"), ("gudem", "guda"), ("ee", "i"), ("oo", "u"),
                 ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("w", "v"), ("aa", "a"), ("z", "j")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def _district(name: str) -> str:
    return re.split(r"[\s-]", name.strip().lower())[0]  # "Medchal-Malkajgiri" and "Medchal Malkajgiri"


@lru_cache(maxsize=1)
def _survey() -> dict:
    by_village = {}
    for w in json.loads(WATER_BODIES_FILE.read_text(encoding="utf-8")):
        by_village.setdefault((_district(w["district"]), _squash(w["village"])), []).append(w)
    return by_village


def water_bodies(district: str, mandal: str, village: str) -> list:
    """The survey's water bodies in this village, biggest first; [] when the survey doesn't have it."""
    found = _survey().get((_district(district), _squash(village)), [])
    # Two villages of the same name in one district: only trust the one in the same mandal.
    if len({_squash(w["mandal"]) for w in found}) > 1:
        found = [w for w in found if _squash(w["mandal"]) == _squash(mandal)]
    keys = ("name", "survey_no", "acres", "status_2011", "status_2023", "lat", "lon")
    return [{k: w[k] for k in keys} for w in found]
