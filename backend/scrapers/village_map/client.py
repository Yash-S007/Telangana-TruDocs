"""Village Map: a whole village's survey map, on screen and as a printable PDF.

The survey-number outlines are the same public TGRAC village maps the Survey Map tool reads
(fetched, cached and rate-limited by its client), so a village opened in either tool is ready
in both. The PDF puts every outline and survey number on Esri's satellite photo, with the
village name, a north arrow and a "for reference only" note. It is not a certified map.
"""
import io
import math
import re
import time
from datetime import date
from functools import lru_cache

import httpx
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from backend.core.hierarchy import survey_map_village
from backend.core.single_flight import single_flight
from backend.scrapers.survey_map import client as survey_map

# shortcut: Esri's keyless World Imagery (what TGRAC's own viewer uses) is fine for testing;
# before going live, confirm Esri's commercial terms or swap in a licensed provider here.
SATELLITE_EXPORT = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export"
# Esri refuses (HTTP 500) pictures sharper than it holds: 0.3 m a pixel near Hyderabad, 0.6 m
# or coarser in much of rural Telangana. 3000 pixels across is ~190 dpi on A3 and keeps the
# PDF near 2 MB (Esri's own cap is 4096).
SHARPEST_M_PER_PX = 0.6
MAX_PX = 3000
_CACHE_SECONDS = 6 * 3600

MARGIN = 12 * mm
HEADER = 20 * mm
FOOTER = 16 * mm


def fetch_village_map(dmv: str) -> dict:
    """Every parcel of a village on our list, for drawing. Roads and streams have no number."""
    version, parcels = survey_map.fetch_village_parcels(dmv)  # checks the code; NOT_FOUND if no map
    dmv = dmv.strip()
    village = survey_map_village(dmv)
    return {
        "source": "village_map",
        "found": True,
        "dmv": dmv,
        "district": village["district"],
        "mandal": village["mandal"],
        "village": village["village"],
        "map_version": version,
        "parcels": [{
            "survey_no": p["survey_no"] if survey_map._is_survey(p) else "",
            "kind": p["remarks"] or p["kind"],
            "rings": [[[round(x, 6), round(y, 6)] for x, y in ring] for ring in p["rings"]],  # ~0.1 m
        } for p in parcels],
    }


def fetch_village_map_pdf(dmv: str) -> tuple:
    """(pdf bytes, filename). Identical requests at once share one build; repeats are cached."""
    data = fetch_village_map(dmv)
    bucket = int(time.time() // _CACHE_SECONDS)
    pdf = single_flight(("village-map-pdf", data["dmv"], bucket), lambda: _pdf(data["dmv"], bucket))
    name = re.sub(r"[^A-Za-z0-9]+", "-", data["village"]).strip("-") or "village"
    return pdf, f"Village-map-{name}-{data['dmv']}.pdf"


# shortcut: keeps the last 8 PDFs (1-3 MB each, mostly the photo) for 6 hours; move to disk
# or object storage if many people download many different villages.
@lru_cache(maxsize=8)
def _pdf(dmv: str, _bucket: int) -> bytes:
    data = fetch_village_map(dmv)
    page_w, page_h = landscape(A3)
    xs, ys = zip(*(_merc(x, y) for p in data["parcels"] for ring in p["rings"] for x, y in ring))
    # A tall village gets a portrait page.
    if (max(ys) - min(ys)) > (max(xs) - min(xs)):
        page_w, page_h = page_h, page_w
    frame = (MARGIN, MARGIN + FOOTER, page_w - 2 * MARGIN, page_h - 2 * MARGIN - HEADER - FOOTER)
    box = _fit(min(xs), min(ys), max(xs), max(ys), frame[2] / frame[3])
    width_px = round(min(MAX_PX, (box[2] - box[0]) / SHARPEST_M_PER_PX))
    photo = _satellite(box, width_px, round(width_px * frame[3] / frame[2]))
    return _draw(data, (page_w, page_h), frame, box, photo)


def _merc(lon: float, lat: float) -> tuple:
    """Web Mercator metres: the projection the satellite photo is drawn in."""
    return lon * 20037508.34 / 180, math.log(math.tan(math.pi / 4 + lat * math.pi / 360)) * 6378137


def _fit(x0, y0, x1, y1, aspect):
    """The village's box with a little room around it, widened to the frame's shape."""
    pad = 0.03 * max(x1 - x0, y1 - y0)
    half_w, half_h = (x1 - x0) / 2 + pad, (y1 - y0) / 2 + pad
    if half_w / half_h < aspect:
        half_w = half_h * aspect
    else:
        half_h = half_w / aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def _satellite(box, width_px: int, height_px: int):
    """Esri's photo of the box as JPEG bytes, or None. Each refusal (sharper than Esri holds
    there) retries with half the pixels, as the Survey Map page does."""
    for _ in range(4):
        try:
            resp = httpx.get(SATELLITE_EXPORT, timeout=60, headers={"User-Agent": survey_map.USER_AGENT}, params={
                "bbox": ",".join(f"{v:.2f}" for v in box), "bboxSR": "3857", "imageSR": "3857",
                "size": f"{width_px},{height_px}", "format": "jpg", "f": "image",
            })
        except httpx.HTTPError:
            return None
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            return resp.content
        width_px, height_px = width_px // 2, height_px // 2
    return None


def _draw(data: dict, page: tuple, frame: tuple, box: tuple, photo) -> bytes:
    page_w, page_h = page
    fx, fy, fw, fh = frame
    scale = fw / (box[2] - box[0])  # points per metre

    def to_pt(lon, lat):
        x, y = _merc(lon, lat)
        return fx + (x - box[0]) * scale, fy + (y - box[1]) * scale

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=page)
    c.setTitle(f"Village map: {data['village']}")
    c.setAuthor("TruDocs")
    c.setFillColorRGB(1, 1, 1)  # paper white, whatever the viewer shows behind a page
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    # Title, and a north arrow at the right (the photo and outlines are drawn north up).
    c.setFillColorRGB(0.12, 0.16, 0.13)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, page_h - MARGIN - 7 * mm, f"Village Map: {data['village']}")
    c.setFont("Helvetica", 10)
    c.drawString(MARGIN, page_h - MARGIN - 13 * mm, f"{data['mandal']} mandal, {data['district']} district, Telangana")
    ax, ay = page_w - MARGIN - 6 * mm, page_h - MARGIN - 15 * mm
    arrow = c.beginPath()
    arrow.moveTo(ax, ay + 9 * mm)
    arrow.lineTo(ax - 3 * mm, ay)
    arrow.lineTo(ax, ay + 2.5 * mm)
    arrow.lineTo(ax + 3 * mm, ay)
    arrow.close()
    c.drawPath(arrow, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(ax, ay + 10.5 * mm, "N")

    # The map: photo (or plain ground if Esri had none), then outlines, then survey numbers.
    if photo:
        c.drawImage(ImageReader(io.BytesIO(photo)), fx, fy, fw, fh)
    else:
        c.setFillColorRGB(0.93, 0.93, 0.9)
        c.rect(fx, fy, fw, fh, stroke=0, fill=1)
    c.saveState()
    clip = c.beginPath()
    clip.rect(fx, fy, fw, fh)
    c.clipPath(clip, stroke=0, fill=0)
    outline = c.beginPath()
    for p in data["parcels"]:
        for ring in p["rings"]:
            pts = [to_pt(x, y) for x, y in ring]
            outline.moveTo(*pts[0])
            for pt in pts[1:]:
                outline.lineTo(*pt)
            outline.close()
    c.setLineJoin(1)
    for width, gray, alpha in ((1.1, 0, 0.6), (0.45, 1, 1)):  # a dark halo, then the white line
        c.setStrokeColorRGB(gray, gray, gray, alpha)
        c.setLineWidth(width)
        c.drawPath(outline, stroke=1, fill=0)
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0, 0, 0, 0.75)
    for p in data["parcels"]:
        if p["survey_no"]:
            _label(c, p["survey_no"], [to_pt(x, y) for ring in p["rings"] for x, y in ring])
    c.restoreState()
    c.setStrokeColorRGB(0.12, 0.16, 0.13)
    c.setLineWidth(0.8)
    c.rect(fx, fy, fw, fh, stroke=1, fill=0)

    # The notes under the map.
    older = data["map_version"] == "2.5m"
    notes = [
        "For reference only: not a certified copy and not a legal survey.",
        "Survey boundaries: TGRAC village maps ("
        + ("older 2.5 m map, so outlines can sit 20-50 m from the real spot" if older else "30 cm map")
        + ")." + ("" if photo else " The satellite photo was unavailable when this PDF was made."),
        f"Satellite photo: Esri, Vantor, Earthstar Geographics. Made with TruDocs on {date.today():%d %b %Y}.",
    ]
    c.setFillColorRGB(0.25, 0.28, 0.26)
    c.setFont("Helvetica", 7.5)
    for i, note in enumerate(notes):
        c.drawString(MARGIN, MARGIN + FOOTER - 6 * mm - i * 3.6 * mm, note)
    c.showPage()
    c.save()
    return buf.getvalue()


def _label(c, text: str, pts: list) -> None:
    """The survey number in the middle of its parcel, as large as the parcel allows: white on a
    dark edge so it reads on any photo. Small ones are tiny but sharp when zoomed in."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    size = max(1.2, min(9, 0.45 * h, 0.85 * w / (0.56 * len(text))))
    x = (min(xs) + max(xs)) / 2 - c.stringWidth(text, "Helvetica-Bold", size) / 2
    y = (min(ys) + max(ys)) / 2 - size * 0.35
    c.setLineWidth(size * 0.28)
    # One text block: the dark edge first, then the white letters on top. (The PDF keeps the
    # outline-only mode between blocks, so a second block would stroke again.)
    t = c.beginText()
    t.setFont("Helvetica-Bold", size)
    for mode in (1, 0):
        t.setTextRenderMode(mode)
        t.setTextOrigin(x, y)
        t.textOut(text)
    c.drawText(t)
