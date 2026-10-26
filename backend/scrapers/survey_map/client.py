"""Survey Map — survey-number boundaries from TGRAC's public ArcGIS server.

Source: the village maps behind TGRAC's public Land Information System viewer
(tgrac.telangana.gov.in/digitallandsurvey/lis/Default.aspx), digitised survey-number
polygons for all of Telangana in WGS84 lat/long. No login, captcha or OTP. Only base
survey numbers ("163"), no sub-divisions ("163/అ").

Measured live: finding a village's parcels takes 13-60s (the server scans the whole layer
on every where-clause), but fetching shapes by ID takes under a second. So a village is
fetched once — its IDs, then its shapes in chunks — and cached: it is public map data,
not personal. The same service also publishes a farmer database layer (names, mobile
numbers); this client only ever asks for survey number and land-type fields.
"""
import math
import re
import threading
from functools import lru_cache

import httpx

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.core.hierarchy import survey_map_village
from backend.core.rate_limit import RateLimiter
from backend.core.single_flight import single_flight

_SERVER = "https://tgrac.telangana.gov.in/arcgis/rest/services"
# Two copies of the village maps, tried in this order. The "30 cm" one is aligned to sharp
# satellite imagery but lacks about 1 village in 4 (7 of 30 sampled); those come from
# Bhunaksha's older "2.5 m" copy, whose shapes sit a median 20 m (90% within 51 m, rare ones
# 150-230 m) from the 30 cm ones in villages both have.
SOURCES = (
    {"map": "30cm", "url": f"{_SERVER}/LIS_Folder/LandInformationSystem_Query/MapServer/0/query",
     "code": "DMV_1991", "survey": "Base_Syno"},
    {"map": "2.5m", "url": f"{_SERVER}/Bhunaksha_Folder/Bhunaksha_query/MapServer/0/query",
     "code": "DMV_Code", "survey": "Parcel_num"},
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CHUNK = 500  # shapes per request; the server caps a reply at 1000 features

_throttle = RateLimiter(min_interval_seconds=0.5)

# Measured live: the server runs about 2 searches at once and fails anything still queued
# after 60s (10 new villages at once: all 10 failed at ~62s). So at most 2 of ours are on
# its side at a time; the rest wait here, and give up politely if the wait gets too long.
_portal_slots = threading.BoundedSemaphore(2)
QUEUE_WAIT_SECONDS = 150

_DMV_RE = re.compile(r"[0-9]{1,10}")  # not \d: that also matches Telugu and other non-ASCII digits
_SURVEY_RE = re.compile(r"[^\x00-\x1f]{1,30}")


def _check_dmv(dmv: str) -> str:
    # Only codes from our village list: this value goes into the server's where-clause, and
    # each unknown code would still cost the government server a 13s scan.
    dmv = (dmv or "").strip()
    if not _DMV_RE.fullmatch(dmv) or survey_map_village(dmv) is None:
        raise PortalError(BAD_INPUT, "unknown village code")
    return dmv


def _query(client: httpx.Client, url: str, **params) -> dict:
    try:
        _throttle.wait()
        resp = client.post(url, data={**params, "f": "json"})
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException as exc:
        raise PortalError(PORTAL_TIMEOUT, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:  # ValueError: an HTML error page instead of JSON
        raise PortalError(PORTAL_DOWN, str(exc)) from exc
    if "error" in data:
        raise PortalError(PORTAL_DOWN, f"arcgis error {data['error'].get('code')}")
    return data


def _parcels(features: list, survey_field: str) -> tuple:
    out = []
    for f in features:
        a = f.get("attributes") or {}
        # a ring under 3 points isn't a shape, and would break the area and framing maths
        rings = [r for r in (f.get("geometry") or {}).get("rings") or [] if len(r) >= 3]
        if rings:
            out.append({
                "survey_no": str(a.get(survey_field) or "").strip(),
                "kind": (a.get("Descriptio") or "").strip(),
                "remarks": (a.get("Remarks") or "").strip(),
                "rings": rings,
            })
    return tuple(out)


@lru_cache(maxsize=128)
def _village_parcels(dmv: str) -> tuple:
    """(map version, parcels) from the first copy that has this village, else (None, ()).
    The empty answer is cached too, so a village without a map isn't re-scanned."""
    if not _portal_slots.acquire(timeout=QUEUE_WAIT_SECONDS):
        raise PortalError(PORTAL_TIMEOUT, "waited too long for a free slot on the TGRAC server")
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90.0) as client:
            for src in SOURCES:
                ids = _query(client, src["url"], where=f"{src['code']}='{dmv}'", returnIdsOnly="true")
                ids = sorted(ids.get("objectIds") or [])
                if not ids:
                    continue
                features = []
                for i in range(0, len(ids), CHUNK):
                    features += _query(
                        client, src["url"], objectIds=",".join(map(str, ids[i:i + CHUNK])),
                        outFields=f"{src['survey']},Descriptio,Remarks", returnGeometry="true", outSR="4326",
                    ).get("features") or []
                return src["map"], _parcels(features, src["survey"])
    finally:
        _portal_slots.release()
    return None, ()


def fetch_village_parcels(dmv: str) -> tuple:
    """(map version, parcels) for a village on our list."""
    dmv = _check_dmv(dmv)
    version, parcels = single_flight(("survey-map", dmv), lambda: _village_parcels(dmv))
    if not parcels:
        raise PortalError(NOT_FOUND, "no survey map for this village")
    return version, parcels


def _natural(s: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _is_survey(p: dict) -> bool:
    # Roads, streams and the village settlement are drawn too, but they aren't survey
    # numbers anyone owns ("UnSurveyed-Road" with numbers like 99901).
    return bool(p["survey_no"]) and not p["kind"].lower().startswith("unsurveyed")


def fetch_survey_options(dmv: str) -> list:
    options = {}
    for p in fetch_village_parcels(dmv)[1]:
        if _is_survey(p):
            options[p["survey_no"]] = f"{p['survey_no']} ({p['remarks']})" if p["remarks"] else p["survey_no"]
    if not options:  # e.g. a map holding only the village outline
        raise PortalError(NOT_FOUND, "village map has no survey numbers")
    return [{"value": v, "label": options[v]} for v in sorted(options, key=_natural)]


def _bbox(rings: list) -> tuple:
    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    return min(xs), min(ys), max(xs), max(ys)


def _signed_area_m2(ring: list) -> float:
    # Shoelace on a local projection; WGS84 radii at the ring's latitude are accurate to
    # well under 1% at parcel scale.
    lat0 = math.radians(sum(y for _, y in ring) / len(ring))
    a, e2 = 6378137.0, 0.00669437999014
    w = 1 - e2 * math.sin(lat0) ** 2
    m_per_rad_y = a * (1 - e2) / w ** 1.5
    m_per_rad_x = a / w ** 0.5 * math.cos(lat0)
    pts = [(math.radians(x) * m_per_rad_x, math.radians(y) * m_per_rad_y) for x, y in ring]
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) / 2


def _acres_guntas(sq_m: float) -> dict:
    gts = round(sq_m / 4046.8564224 * 40)  # 1 acre = 40 guntas
    return {"acres": gts // 40, "guntas": gts % 40}


def fetch_parcel(dmv: str, survey_no: str) -> dict:
    survey_no = (survey_no or "").strip()
    if not _SURVEY_RE.fullmatch(survey_no):
        raise PortalError(BAD_INPUT, "invalid survey number")
    version, parcels = fetch_village_parcels(dmv)  # validates dmv
    mine = [p for p in parcels if p["survey_no"] == survey_no and _is_survey(p)]
    if not mine:
        raise PortalError(NOT_FOUND, "survey number not on this village's map")
    rings = [r for p in mine for r in p["rings"]]

    corners = []
    for ring in rings:
        pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
        corners += [{"label": f"P{len(corners) + i + 1}", "lat": round(y, 7), "lon": round(x, 7)}
                    for i, (x, y) in enumerate(pts)]
    # Esri rings: outer clockwise, holes anticlockwise, so the sum is outer minus holes.
    sq_m = abs(sum(_signed_area_m2(r) for r in rings))

    x0, y0, x1, y1 = _bbox(rings)
    pad = max(x1 - x0, y1 - y0)
    near = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    neighbours = []
    for p in parcels:
        if p in mine:
            continue
        a0, b0, a1, b1 = _bbox(p["rings"])
        if a0 <= near[2] and a1 >= near[0] and b0 <= near[3] and b1 >= near[1]:
            neighbours.append({"survey_no": p["survey_no"] if _is_survey(p) else "",
                               "kind": p["remarks"] or p["kind"], "rings": p["rings"]})

    village = survey_map_village(dmv.strip())
    return {
        "source": "survey_map",
        "found": True,
        "district": village["district"],
        "mandal": village["mandal"],
        "village": village["village"],
        "survey_no": survey_no,
        "remarks": mine[0]["remarks"],
        "map_version": version,
        "area_sq_m": round(sq_m),
        "area_acres": round(sq_m / 4046.8564224, 2),
        "area_ac_gts": _acres_guntas(sq_m),
        "corners": corners,
        "centre": {"lat": round((y0 + y1) / 2, 7), "lon": round((x0 + x1) / 2, 7)},
        "rings": rings,
        "neighbours": neighbours,
    }
