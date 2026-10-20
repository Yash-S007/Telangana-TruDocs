"""Village Map: the whole-village data for drawing, and its PDF. Synthetic shapes only; the
village code is a real one from our list (codes are public, not personal)."""
import io
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.routers import village_map as village_map_router
from backend.scrapers.survey_map import client as survey_map
from backend.scrapers.village_map import client

DMV = "1516004"  # Kokapet, Gandipet, Rangareddy


def square(x0, y0, d=0.0009):
    return [[x0, y0], [x0, y0 + d], [x0 + d, y0 + d], [x0 + d, y0], [x0, y0]]


PARCELS = (
    {"survey_no": "163", "kind": "Surveyed", "remarks": "Patta", "rings": [square(78.3201234567, 17.4001234567)]},
    {"survey_no": "164", "kind": "Surveyed", "remarks": "", "rings": [square(78.3211, 17.4001)]},
    {"survey_no": "99901", "kind": "UnSurveyed-Road", "remarks": "", "rings": [square(78.3221, 17.4001, 0.0003)]},
)


@pytest.fixture(autouse=True)
def fresh():
    client._pdf.cache_clear()
    yield
    client._pdf.cache_clear()


@pytest.fixture
def portal(monkeypatch):
    calls = []

    def fetch(dmv):
        calls.append(dmv)
        if dmv.strip() != DMV:
            raise PortalError(NOT_FOUND, "no survey map for this village")
        return "30cm", PARCELS

    monkeypatch.setattr(survey_map, "fetch_village_parcels", fetch)
    return calls


@pytest.fixture
def photo(monkeypatch):
    jpeg = io.BytesIO()
    Image.new("RGB", (40, 30), (60, 90, 50)).save(jpeg, "JPEG")
    asked = []
    monkeypatch.setattr(client, "_satellite", lambda box: asked.append(box) or jpeg.getvalue())
    return asked


def _app():
    app = FastAPI()
    app.include_router(village_map_router.router)
    return TestClient(app)


def test_map_has_every_parcel_and_numbers_only_on_surveys(portal):
    data = _app().get(f"/api/village-map/map/{DMV}").json()
    assert (data["village"], data["mandal"], data["district"], data["map_version"]) == ("Kokapet", "Gandipet", "Rangareddy", "30cm")
    assert [p["survey_no"] for p in data["parcels"]] == ["163", "164", ""]  # roads and streams have no number
    assert data["parcels"][0]["rings"][0][0] == [78.320123, 17.400123]  # ~0.1 m is plenty to draw


def test_unknown_village_codes_never_reach_the_portal(monkeypatch):
    monkeypatch.setattr(survey_map, "_village_parcels", lambda dmv: pytest.fail("portal called"))
    for dmv in ("123", "abc", "1516004'--"):
        resp = _app().get(f"/api/village-map/map/{dmv}")
        assert resp.status_code == 400 and resp.json()["detail"] == BAD_INPUT


def test_village_without_a_map_is_a_friendly_not_found(portal):
    resp = _app().get("/api/village-map/map/1903030")
    assert resp.status_code == 404 and resp.json()["detail"] == NOT_FOUND


def test_pdf_opens_in_the_tab_with_a_clear_name(portal, photo):
    resp = _app().get(f"/api/village-map/pdf/{DMV}")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="Village-map-Kokapet-1516004.pdf"'
    assert resp.content.startswith(b"%PDF-") and b"(Village map: Kokapet)" in resp.content
    (box,) = photo
    assert (box[2] - box[0]) / (box[3] - box[1]) > 1.3  # a landscape A3 frame for a wide village


def test_pdf_is_still_made_when_the_photo_is_unavailable(portal, monkeypatch):
    monkeypatch.setattr(client, "_satellite", lambda box: None)
    pdf, name = client.fetch_village_map_pdf(DMV)
    assert pdf.startswith(b"%PDF-") and name == "Village-map-Kokapet-1516004.pdf"


def test_pdf_errors_are_a_readable_page(photo, monkeypatch):
    monkeypatch.setattr(survey_map, "_village_parcels", lambda dmv: pytest.fail("portal called"))
    resp = _app().get("/api/village-map/pdf/123")
    assert resp.status_code == 400 and resp.headers["content-type"].startswith("text/html")
    assert BAD_INPUT.replace("'", "&#x27;") in resp.text


def test_identical_pdf_requests_share_one_build_and_repeats_are_cached(portal, photo, monkeypatch):
    builds = []
    real = client._draw

    def slow_draw(*args):
        builds.append(1)
        time.sleep(0.3)
        return real(*args)

    monkeypatch.setattr(client, "_draw", slow_draw)
    results = []
    threads = [threading.Thread(target=lambda: results.append(client.fetch_village_map_pdf(DMV)[0])) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    client.fetch_village_map_pdf(DMV)
    assert len(builds) == 1 and len(set(results)) == 1


def _tiles(monkeypatch, fail=lambda tx, ty: False):
    """Esri tiles as solid squares; returns the (level, tx, ty) asked for."""
    asked, jpeg = [], io.BytesIO()
    Image.new("RGB", (256, 256), (200, 30, 30)).save(jpeg, "JPEG")
    monkeypatch.setattr(client, "_tile", lambda c, level, tx, ty: asked.append((level, tx, ty)) or (None if fail(tx, ty) else jpeg.getvalue()))
    return asked


BOX = (8716200.0, 1966000.0, 8721000.0, 1969000.0)  # 4.8 km x 3 km of Web Mercator around Kokapet


def test_photo_is_stitched_at_the_nearest_level_and_cropped_to_the_map(monkeypatch):
    asked = _tiles(monkeypatch)
    photo = Image.open(io.BytesIO(client._satellite(BOX)))
    level = asked[0][0]
    size = 2 * client.WORLD / 2 ** level
    assert level == 16 and len({(tx, ty) for _, tx, ty in asked}) == len(asked)  # each tile once
    assert abs(photo.width - (BOX[2] - BOX[0]) / size * 256) <= 1 and abs(photo.height - (BOX[3] - BOX[1]) / size * 256) <= 1
    assert client.PHOTO_PX / 2 ** 0.5 <= photo.width <= client.MAX_PHOTO_PX


def test_a_photo_wider_than_needed_is_scaled_down(monkeypatch):
    _tiles(monkeypatch)
    photo = Image.open(io.BytesIO(client._satellite((8716200.0, 1966000.0, 8719900.0, 1968000.0))))  # 3.7 km: ~3100 px
    assert photo.width == client.MAX_PHOTO_PX


def test_missing_tiles_leave_grey_and_no_tiles_means_no_photo(monkeypatch):
    _tiles(monkeypatch, fail=lambda tx, ty: tx % 2 == 0)
    assert Image.open(io.BytesIO(client._satellite(BOX))).width > 1000
    _tiles(monkeypatch, fail=lambda tx, ty: True)
    assert client._satellite(BOX) is None


def test_a_broken_tile_is_left_grey(monkeypatch):
    asked, good = [], io.BytesIO()
    Image.new("RGB", (256, 256), (200, 30, 30)).save(good, "JPEG")
    monkeypatch.setattr(client, "_tile", lambda c, level, tx, ty: asked.append(tx) or (b"\xff\xd8 not a jpeg" if tx % 2 else good.getvalue()))
    assert Image.open(io.BytesIO(client._satellite(BOX))).width > 1000


def test_at_most_two_pdfs_are_built_at_once(portal, monkeypatch):
    villages = ("1516004", "1903030", "2036023", "1901022")  # real codes from our list
    monkeypatch.setattr(survey_map, "fetch_village_parcels", lambda dmv: ("30cm", PARCELS))
    monkeypatch.setattr(client, "_satellite", lambda box: None)
    running, peak, lock = [0], [0], threading.Lock()
    real = client._draw

    def counted(*args):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.2)
        try:
            return real(*args)
        finally:
            with lock:
                running[0] -= 1

    monkeypatch.setattr(client, "_draw", counted)
    threads = [threading.Thread(target=client.fetch_village_map_pdf, args=(v,)) for v in villages]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] == 2


def test_a_huge_village_gets_a_coarser_photo_not_hundreds_of_tiles(monkeypatch):
    asked = _tiles(monkeypatch)
    client._satellite((8700000.0, 1950000.0, 8760000.0, 1990000.0))  # 60 km wide
    assert len(asked) <= client.MAX_TILES


def test_photo_gives_up_quietly_when_esri_is_unreachable(monkeypatch):
    def down(self, url, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(client.httpx.Client, "get", down)
    assert client._satellite(BOX) is None
