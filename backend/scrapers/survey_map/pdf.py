"""Survey Map as a PDF: the page's map (the survey number on the satellite photo, its neighbours
and their numbers, its corner points) with its area, centre and every corner's GPS point."""
import io

import httpx
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, Spacer

from backend.core import pdf
from backend.scrapers.survey_map import client as survey_map
from backend.scrapers.village_map.client import _label, _merc

# shortcut: Esri's keyless World Imagery (what TGRAC's own viewer uses) is fine for testing;
# before going live, confirm Esri's commercial terms or swap in a licensed provider here.
SATELLITE_EXPORT = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export"
MAP_W, MAP_H = 180 * mm, 135 * mm  # the page's 4:3 map, across the A4 page
GOLD = colors.HexColor("#f5c45e")  # the page's accent


def fetch_parcel_pdf(dmv: str, survey_no: str) -> tuple:
    """(pdf bytes, filename). The village's map is cached, so this costs TGRAC nothing after the
    look-up; the photo comes from Esri."""
    data = survey_map.fetch_parcel(dmv, survey_no)
    box = _frame(data["rings"])
    photo = _photo(box)
    acres, guntas = data["area_ac_gts"]["acres"], data["area_ac_gts"]["guntas"]
    details = [("Area (approx.)", f"{acres} acres {guntas} guntas · {data['area_sq_m']:,} m²"),
               *([("Land note", data["remarks"])] if data["remarks"] else []),
               ("Centre", f"{data['centre']['lat']}, {data['centre']['lon']}"),
               ("Map version", "Older 2.5 m map: the outline can sit 20-50 m from the real spot" if data["map_version"] == "2.5m"
                else "30 cm map, matched to sharp satellite imagery")]
    p = pdf.para
    story = [p(f"Survey Map: Survey No. {data['survey_no']}", "title"),
             p(f"{data['village']} village, {data['mandal']} mandal, {data['district']} district, Telangana", "sub"),
             Spacer(0, 5 * mm), _Map(data, box, photo),
             *([] if photo else [p("The satellite photo was unavailable when this PDF was made.", "sub")]),
             p("Details", "head"), pdf.fields(details),
             p(f"{len(data['corners'])} corner points", "head"),
             pdf.cells([[p(h, "label") for h in ("CORNER", "LATITUDE", "LONGITUDE")]]
                       + [[p(c["label"], "cell"), p(c["lat"], "cell"), p(c["lon"], "cell")] for c in data["corners"]],
                       [30 * mm, 75 * mm, 75 * mm], header=True)]
    content = pdf.build(story, title=f"Survey map: survey no. {data['survey_no']}, {data['village']}",
                        note="Approximate, for reference only: not a legal survey. Traced from digitised government village maps.",
                        source="TGRAC village maps; photo: Esri, Vantor, Earthstar Geographics")
    return content, pdf.filename("Survey-map", data["village"], data["survey_no"])


def _frame(rings: list) -> tuple:
    """As on the page: the parcel with room for its neighbours, at least 200 m across, at the
    map's 4:3 shape, in Web Mercator metres."""
    xs, ys = zip(*(_merc(x, y) for ring in rings for x, y in ring))
    pad = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.6
    half_w, half_h = max((max(xs) - min(xs)) / 2 + pad, 100), (max(ys) - min(ys)) / 2 + pad
    if half_w / half_h < MAP_W / MAP_H:
        half_w = half_h * MAP_W / MAP_H
    else:
        half_h = half_w * MAP_H / MAP_W
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def _photo(box: tuple):
    """Esri's photo of the frame (JPEG bytes), or None. As on the page: ~0.31 m a pixel, up to 1280
    pixels, and half the pixels each time Esri refuses (HTTP 500: it has nothing that sharp there)."""
    width = round(min(1280, (box[2] - box[0]) / 0.31))
    with httpx.Client(headers={"User-Agent": survey_map.USER_AGENT}, timeout=30) as client:
        for _ in range(4):
            try:
                resp = client.get(SATELLITE_EXPORT, params={
                    "bbox": ",".join(f"{v:.2f}" for v in box), "bboxSR": "3857", "imageSR": "3857",
                    "size": f"{width},{round(width * MAP_H / MAP_W)}", "format": "jpg", "f": "image"})
            except httpx.HTTPError:
                return None
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
                return resp.content
            width //= 2
    return None


class _Map(Flowable):
    """The photo (or plain ground), the neighbours' outlines and numbers, the parcel in gold on a
    dark halo, and its corner points, labelled when there are 20 or fewer."""

    def __init__(self, data: dict, box: tuple, photo):
        super().__init__()
        self.data, self.box, self.photo = data, box, photo
        self.width, self.height = MAP_W, MAP_H

    def draw(self):
        c, (x0, y0, x1, _) = self.canv, self.box
        scale = MAP_W / (x1 - x0)  # points per metre

        def points(ring):
            return [((mx - x0) * scale, (my - y0) * scale) for mx, my in (_merc(x, y) for x, y in ring)]

        def path(rings):
            shape = c.beginPath()
            for ring in rings:
                first, *rest = points(ring)
                shape.moveTo(*first)
                for xy in rest:
                    shape.lineTo(*xy)
                shape.close()
            return shape

        if self.photo:
            c.drawImage(ImageReader(io.BytesIO(self.photo)), 0, 0, MAP_W, MAP_H)
        else:
            c.setFillColorRGB(0.93, 0.93, 0.9)
            c.rect(0, 0, MAP_W, MAP_H, stroke=0, fill=1)
        c.saveState()
        frame = c.beginPath()
        frame.rect(0, 0, MAP_W, MAP_H)
        c.clipPath(frame, stroke=0, fill=0)
        c.setLineJoin(1)
        c.setStrokeColorRGB(1, 1, 1, 0.8)
        c.setLineWidth(0.6)
        for n in self.data["neighbours"]:
            c.drawPath(path(n["rings"]), stroke=1, fill=0)
        own = path(self.data["rings"])
        c.setStrokeColorRGB(0, 0, 0, 0.55)
        c.setLineWidth(3.4)
        c.drawPath(own, stroke=1, fill=0)
        c.saveState()  # the see-through fill mustn't fade what's drawn after it
        c.setStrokeColor(GOLD)
        c.setFillColor(GOLD, alpha=0.22)
        c.setLineWidth(1.7)
        c.drawPath(own, stroke=1, fill=1)
        c.restoreState()
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(0, 0, 0, 0.75)
        for n in self.data["neighbours"]:
            if n["survey_no"]:
                _label(c, n["survey_no"], [xy for ring in n["rings"] for xy in points(ring)], biggest=7)
        _label(c, self.data["survey_no"], [xy for ring in self.data["rings"] for xy in points(ring)], biggest=14)
        corners = self.data["corners"]
        for corner in corners:
            (x, y), = points([(corner["lon"], corner["lat"])])
            c.setFillColor(GOLD)
            c.setStrokeColorRGB(1, 1, 1)
            c.setLineWidth(0.8)
            c.circle(x, y, 2.4, stroke=1, fill=1)
            if len(corners) <= 20:  # beyond that the labels pile on top of each other
                c.setFillColorRGB(1, 1, 1)
                c.setStrokeColorRGB(0, 0, 0, 0.75)
                _label(c, corner["label"], [(x + 2, y + 2), (x + 18, y + 17)], biggest=6.5)  # up and right of the point
        c.restoreState()
        c.setStrokeColorRGB(0.12, 0.16, 0.13)
        c.setLineWidth(0.8)
        c.rect(0, 0, MAP_W, MAP_H, stroke=1, fill=0)
