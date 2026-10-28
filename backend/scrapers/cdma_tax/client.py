"""CDMA Property Tax Receipt — the property tax portal of the Commissioner & Director of
Municipal Administration (cdma.cgg.gov.in), which serves every Telangana town outside GHMC.

No login, captcha, OTP or cookie. Everything is a JSON POST to /CDMA_ARBS/CDMA_PG/…:
  GetReciptDetails {PTNO}              the PTIN's receipts, a table (~0.1 s)
  GetPTDetails_PV {PTNO}               owner, address and the tax due today (~1 s)
  BindPTSearchDetail_PV {Param}        find a PTIN by town + door number or owner name
  GetPTForDownload {MID, PTINNO, SLNO} one receipt as a web page — the portal takes 14-50 s
The receipt page's own script then posts its HTML to /Download, and the portal answers with
the official PDF (seal watermark and QR code) in about a second. We do the same.
A look-up is also our own PDF (fetch_property_pdf): owner, tax due and receipts, watermarked
"Only For Information" — the official receipts stay the portal's, untouched.
"""
import json
import re
import time
from datetime import datetime
from functools import lru_cache
from html import unescape
from pathlib import Path

import httpx
from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from backend.core import pdf
from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.rate_limit import RateLimiter
from backend.core.single_flight import single_flight

BASE_URL = "https://cdma.cgg.gov.in/CDMA_ARBS/CDMA_PG"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TOWNS_FILE = Path(__file__).resolve().parents[2] / "data" / "cdma_towns.json"
MAX_FOUND = 100  # a 3-letter owner name can match hundreds of properties in a big town
TITLE = "Property Tax Receipt (CDMA)"  # the tool's name, on its PDFs' front page

_throttle = RateLimiter(min_interval_seconds=1.0)  # at most 60 requests a minute to this portal

# Dues change when someone pays, and people look up the receipt right after paying, so a
# lookup is reused for 5 minutes only. Receipts never change once issued.
_LOOKUP_SECONDS = 5 * 60
_RECEIPT_SECONDS = 6 * 3600

_PTIN_RE = re.compile(r"[0-9]{10}")  # not \d: that also matches Telugu and other non-ASCII digits
_RECEIPT_NO_RE = re.compile(r"[A-Za-z0-9/_-]{1,40}")
_SLNO_RE = re.compile(r"[0-9]{1,25}")
# The portal's own rules for these boxes, minus the comma (it joins the search fields with
# commas), with a 3-character minimum: one letter matches tens of thousands of properties.
_OWNER_RE = re.compile(r"[A-Za-z .]{3,50}")
_DOOR_RE = re.compile(r"[A-Za-z0-9 &./-]{3,30}")
DOOR_CHARS = "A door number has English letters, digits, spaces and & . / - only, like 8-1-43."
OWNER_CHARS = "Type the owner's name in English letters, as on the tax records."
_NO_RECORDS = "No Records found"


def _send(client: httpx.Client, path: str, body: dict) -> str:
    try:
        _throttle.wait()
        resp = client.post(path, content=json.dumps(body), headers={"Content-Type": "application/json; charset=utf-8"})
        resp.raise_for_status()
        return resp.text
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise PortalError(PORTAL_DOWN, str(exc)) from exc


def _client(timeout: float = 60.0) -> httpx.Client:
    # The portal sometimes drops a new connection mid-handshake (seen live: SSL EOF after 15 s)
    # while the next one works; connect once more. Only connecting is retried, so nothing is sent twice.
    return httpx.Client(base_url=BASE_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout,
                        transport=httpx.HTTPTransport(retries=1))


def _text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _ptin(ptin: str) -> str:
    ptin = (ptin or "").strip()
    if not _PTIN_RE.fullmatch(ptin):
        raise PortalError(BAD_INPUT, "a PTIN is 10 digits")
    return ptin


def _table(html: str, table_id: str) -> tuple:
    """(lower-cased headings, [(row html, [cell texts])]) of the portal table with this id."""
    m = re.search(rf'<table[^>]*id="{table_id}".*?</table>', html, re.S)
    if not m:
        return [], []
    heads = [_text(h).lower() for h in re.findall(r"<th\b[^>]*>(.*?)</th>", m.group(0), re.S)]
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", m.group(0), re.S):
        cells = [_text(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= len(heads) > 0:
            rows.append((row, cells))
    return heads, rows


def _amount(value: str):
    m = re.search(r"-?\d+(?:\.\d+)?", value or "")
    if not m:
        return None
    n = float(m.group(0))
    return int(n) if n.is_integer() else n


@lru_cache(maxsize=1)
def towns() -> list:
    """Districts and their towns for the "find your PTIN" search (scrape_cdma_towns.py)."""
    return json.loads(TOWNS_FILE.read_text(encoding="utf-8"))


def _district_of(town_id: str) -> int:
    for d in towns():
        if any(str(t["id"]) == town_id for t in d["towns"]):
            return d["district_id"]
    raise PortalError(BAD_INPUT, "unknown town")


def find_properties(town_id: str, door_no: str = "", owner_name: str = "") -> dict:
    """Properties in a town matching a door number or owner name (the portal matches parts)."""
    town_id = (town_id or "").strip()
    district_id = _district_of(town_id)
    door_no, owner_name = " ".join((door_no or "").split()), " ".join((owner_name or "").split())
    if not door_no and not owner_name:
        raise PortalError(BAD_INPUT, "enter a door number or an owner name")
    if door_no and not _DOOR_RE.fullmatch(door_no):
        raise PortalError(DOOR_CHARS, "door numbers use letters, digits, spaces and & . / - only, at least 3 characters")
    if owner_name and not _OWNER_RE.fullmatch(owner_name):
        raise PortalError(OWNER_CHARS, "owner names use letters, spaces and dots only, at least 3 characters")
    with _client() as client:
        html = _send(client, "/BindPTSearchDetail_PV", {"Param": f"{district_id},,{owner_name},{door_no},{town_id}"})
    heads, rows = _table(html, "demoGrid")
    col = {name: heads.index(name) for name in ("pt number", "locality name", "owner name", "door number") if name in heads}
    if len(col) < 4:
        if _NO_RECORDS in html:
            raise PortalError(NOT_FOUND, "no property matches")
        raise PortalError(PORTAL_DOWN, f"unexpected search page, columns {heads}")
    found = [{
        "ptin": cells[col["pt number"]],
        "owner": cells[col["owner name"]].rstrip(" ."),
        "door_no": cells[col["door number"]],
        "locality": cells[col["locality name"]],
    } for _, cells in rows if _PTIN_RE.fullmatch(cells[col["pt number"]])]
    if not found:
        raise PortalError(NOT_FOUND, "no property matches")
    return {"total": len(found), "shown": min(len(found), MAX_FOUND), "properties": found[:MAX_FOUND]}


def fetch_property(ptin: str) -> dict:
    """A PTIN's owner, address, tax due today and every receipt the portal has for it."""
    ptin = _ptin(ptin)
    bucket = int(time.time() // _LOOKUP_SECONDS)
    return single_flight(("cdma-tax", ptin, bucket), lambda: _lookup(ptin, bucket))


# shortcut: per-process cache (5-minute buckets); move to Redis if we run more than one instance.
@lru_cache(maxsize=256)
def _lookup(ptin: str, _bucket: int) -> dict:
    with _client() as client:
        receipts_html = _send(client, "/GetReciptDetails", {"PTNO": ptin})
        dues_html = _send(client, "/GetPTDetails_PV", {"PTNO": ptin})
    receipts = _parse_receipts(receipts_html)
    details = _parse_details(dues_html)
    if receipts is None and details is None:
        raise PortalError(NOT_FOUND, "the portal has no property with this PTIN")
    return {"source": "cdma_tax", "found": True, "ptin": ptin, **(details or {"property": None, "dues": None}), "receipts": receipts or []}


def _parse_receipts(html: str):
    """The receipt rows, or None when the portal has none for this PTIN."""
    heads, rows = _table(html, "tblPrintRecipt")
    col = {name: heads.index(name) for name in ("receipt date", "paid from", "paid to", "receipt no.", "payment gateway", "amount") if name in heads}
    if len(col) < 6:
        if _NO_RECORDS in html:
            return None
        raise PortalError(PORTAL_DOWN, f"unexpected receipts page, columns {heads}")
    receipts = []
    for row, cells in rows:
        link = re.search(r"DownloadPDF\('\s*([^'\s]*)\s*'\s*,\s*'\s*(\d+)\s*'\)", row)
        receipts.append({
            "date": cells[col["receipt date"]],
            "paid_from": cells[col["paid from"]],
            "paid_to": cells[col["paid to"]],
            "receipt_no": cells[col["receipt no."]],
            "mode": cells[col["payment gateway"]],
            "amount": _amount(cells[col["amount"]]),
            # only receipts the portal offers a download for get a PDF link
            "slno": link.group(2) if link and link.group(1) == cells[col["receipt no."]] else "",
        })
    return receipts or None


def _pairs(html: str) -> dict:
    """lower-cased label → value from the portal's "Label : value" table rows."""
    pairs = {}
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S):
        cells = [_text(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)]
        for i, label in enumerate(cells[:-1]):
            value = cells[i + 1]
            if value == ":" and i + 2 < len(cells):
                value = cells[i + 2]
            elif value.startswith(":"):
                value = value[1:].strip()
            else:
                continue
            pairs.setdefault(re.sub(r"\(\s*\)$", "", label).strip().lower(), value)
    return pairs


def _parse_details(html: str):
    """Property details and the dues summary, or None when the portal has no such PTIN."""
    if "Property Tax Details" not in html:
        if _NO_RECORDS in html:
            return None
        raise PortalError(PORTAL_DOWN, "unexpected property details page")
    p = _pairs(html)
    as_on = re.search(r"Due as on\s*-\s*(?:<[^>]+>\s*)*([\d/-]+)", html)
    adjustment = next((v for k, v in p.items() if k.startswith("adjustment amount")), "")
    return {
        "property": {
            # the portal fills a "(S/O (or) D/O (or) W/O)" template after the owner's name
            "owner": re.split(r"\s*\(S/O", p.get("name", ""))[0].strip(),
            "door_no": p.get("door number", ""),
            "locality": p.get("locality", ""),
            "town": p.get("ulb", ""),
            "usage": p.get("usage type", ""),
        },
        "dues": {
            "as_on": as_on.group(1) if as_on else "",
            "arrear_tax": _amount(p.get("arrear tax")),
            "arrear_interest": _amount(p.get("arrear interest")),
            "current_tax": _amount(p.get("current tax")),
            "current_interest": _amount(p.get("current interest")),
            "cheque_bounce_penalty": _amount(p.get("cheque bounce penalty")),
            "deviation_penalty": _amount(p.get("deviation penalty")),
            "adjustment": _amount(adjustment),
            "total": _amount(p.get("total amount to pay")),
        },
    }


def fetch_receipt_pdf(ptin: str, receipt_no: str, slno: str) -> tuple:
    """(pdf bytes, filename): the portal's own PDF of one receipt from the lookup's list."""
    ptin, receipt_no, slno = _ptin(ptin), (receipt_no or "").strip(), (slno or "").strip()
    if not _RECEIPT_NO_RE.fullmatch(receipt_no) or not _SLNO_RE.fullmatch(slno):
        raise PortalError(BAD_INPUT, "invalid receipt")
    bucket = int(time.time() // _RECEIPT_SECONDS)
    key = (ptin, receipt_no, slno, bucket)
    return single_flight(("cdma-tax-receipt",) + key, lambda: _receipt_pdf(*key))


# shortcut: keeps the last 64 receipts (~150 KB each) for 6 hours; move to disk or Redis if
# many people open the same receipts or we run more than one instance. Kept with the front page,
# so everyone asking for one shares one copy.
@lru_cache(maxsize=64)
def _receipt_pdf(ptin: str, receipt_no: str, slno: str, _bucket: int) -> tuple:
    with _client(timeout=120.0) as client:  # the portal takes 14-50 s to build a receipt
        page = _send(client, "/GetPTForDownload", {"MID": receipt_no, "PTINNO": ptin, "SLNO": slno})
        grid, qr = _receipt_form(page, ptin)
        try:
            _throttle.wait()
            resp = client.post("/Download", data={"qrFilePath": qr, "GridHtml": grid})
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise PortalError(PORTAL_DOWN, str(exc)) from exc
    if not resp.content.startswith(b"%PDF"):
        raise PortalError(PORTAL_DOWN, "the portal's receipt download is not a PDF")
    return pdf.document(resp.content, TITLE, f"PTIN {ptin}", f"Receipt No. {receipt_no}")


def _receipt_form(page: str, ptin: str) -> tuple:
    """What the receipt page's script posts to /Download: the receipt's HTML and its QR code."""
    start = page.find('<div id="Grid">')
    form = page.find('<form action="/CDMA_ARBS/CDMA_PG/Download"')
    grid = re.sub(r"(?:\s|<br\s*/?>)*$", "", page[start + len('<div id="Grid">'):form])
    if start < 0 or form < start or not grid.endswith("</div>"):
        raise PortalError(PORTAL_DOWN, "unexpected receipt page")
    grid = grid[:-len("</div>")]
    # a receipt number that doesn't belong to this PTIN comes back as an empty receipt, no QR
    if not re.search(rf">\s*{ptin}\s*<", grid):
        raise PortalError(NOT_FOUND, "the portal has no such receipt for this PTIN")
    qr = re.search(r'name="qrFilePath" value="(data:image/png;base64,[A-Za-z0-9+/=]+)"', page)
    if not qr:
        raise PortalError(PORTAL_DOWN, "receipt page without its QR code")
    return grid, qr.group(1)


# ---------- a look-up as a PDF ----------
def fetch_property_pdf(ptin: str) -> tuple:
    """(pdf bytes, filename): what the tool shows for a PTIN (owner, tax due, receipts) as a PDF.
    It reuses the look-up, so right after one it costs the portal nothing."""
    data = fetch_property(ptin)
    return pdf.document(_property_pdf(data, datetime.now(pdf.IST)), TITLE, f"PTIN {data['ptin']}", (data["property"] or {}).get("town"))


def _property_pdf(data: dict, now: datetime) -> bytes:
    p, rupees = pdf.para, pdf.rupees
    prop, dues, receipts = data["property"], data["dues"], data["receipts"]
    story = [p(f"Property Tax Details: PTIN {data['ptin']}", "title"),
             p(f"{prop['town']}, Telangana" if prop and prop["town"] else "Telangana", "sub")]
    if prop:
        story += [Spacer(0, 5 * mm), pdf.cells(
            [[p(k, "label"), p(v, "value")] for k, v in (("OWNER", prop["owner"]), ("DOOR NUMBER", prop["door_no"]),
                                                         ("LOCALITY", prop["locality"]), ("USAGE", prop["usage"]))],
            [42 * mm, 138 * mm])]
    if dues:
        rows = [("ARREAR TAX", dues["arrear_tax"]), ("ARREAR INTEREST", dues["arrear_interest"]),
                ("CURRENT TAX", dues["current_tax"]), ("CURRENT INTEREST", dues["current_interest"]),
                # only when the portal charges them, so the rows add up to the total (as on the page)
                *((k, v) for k, v in (("CHEQUE BOUNCE PENALTY", dues["cheque_bounce_penalty"]),
                                      ("DEVIATION PENALTY", dues["deviation_penalty"]),
                                      ("ADJUSTMENT FROM EARLIER YEARS", dues["adjustment"])) if v)]
        story += [p(f"Tax due as on {dues['as_on']}", "head"), pdf.cells(
            [[p(k, "label"), p(rupees(v), "value")] for k, v in rows] + [[p("TOTAL DUE", "label"), p(rupees(dues["total"]), "total")]],
            [62 * mm, 118 * mm])]
    count = len(receipts)
    story.append(p(f"{count} tax receipt{'' if count == 1 else 's'}" if count else "No tax receipts on the portal for this PTIN yet", "head"))
    if receipts:
        story.append(pdf.cells(
            [[p(h, "label") for h in ("DATE", "AMOUNT", "PERIOD PAID", "MODE", "RECEIPT NO.")]]
            + [[p(r["date"], "cell"), p(rupees(r["amount"]), "cell"), p(f"{r['paid_from']} to {r['paid_to']}", "cell"),
                p(r["mode"], "cell"), p(r["receipt_no"], "cell")] for r in receipts],
            [22 * mm, 26 * mm, 48 * mm, 22 * mm, 62 * mm], header=True))
    return pdf.build(story, title=f"Property tax details: PTIN {data['ptin']}", now=now,
                     note="For reference only: not an official receipt or tax demand. The official receipts are the portal's own PDFs.",
                     source="CDMA property tax portal (cdma.cgg.gov.in)")
