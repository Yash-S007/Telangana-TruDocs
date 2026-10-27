"""Survey Map tests. Synthetic squares near Hyderabad stand in for the government's
shapes (no real records); the TGRAC server is faked except where noted."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from reportlab import rl_config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.routers import survey_map as survey_map_router
from backend.scrapers.survey_map import client
from backend.scrapers.survey_map import pdf as survey_map_pdf

DMV = "1516004"  # a village code from survey_map_villages.json (codes are public, not personal)


def square(x0, y0, d=0.0009):  # ~95 m x 100 m, clockwise like Esri outer rings
    return [[x0, y0], [x0, y0 + d], [x0 + d, y0 + d], [x0 + d, y0], [x0, y0]]


def feature(no, kind, remarks, ring):
    return {"attributes": {"Base_Syno": no, "Descriptio": kind, "Remarks": remarks}, "geometry": {"rings": [ring]}}


FEATURES = [
    feature("10", "Surveyed", " ", square(78.33, 17.38)),
    feature("2", "Surveyed", "Gairan", square(78.3309, 17.38)),
    feature("99901", "UnSurveyed-Road", "Road", square(78.33, 17.3809)),
    feature("300", "Surveyed", "", square(78.40, 17.45)),  # far from 10
]


@pytest.fixture(autouse=True)
def fresh_cache():
    client._village_parcels.cache_clear()
    yield
    client._village_parcels.cache_clear()


LIS_URL, BHUNAKSHA_URL = (s["url"] for s in client.SOURCES)


def fake_portal(monkeypatch, features=FEATURES, delay=0.0, has=(LIS_URL,)):
    """Fake TGRAC server: the map copies in `has` hold `features` for every village."""
    calls = []

    def fake_query(_client, url, **params):
        calls.append((url, params))
        time.sleep(delay)
        if "returnIdsOnly" in params:
            return {"objectIds": list(range(len(features))) if url in has else []}
        return {"features": [features[int(i)] for i in params["objectIds"].split(",")]}

    monkeypatch.setattr(client, "_query", fake_query)
    return calls


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as exc:
        fn(*args, **kwargs)
    assert exc.value.user_message == user_message


def _app():
    app = FastAPI()
    app.include_router(survey_map_router.router)
    return TestClient(app)


def test_survey_options_are_real_survey_numbers_in_natural_order(monkeypatch):
    fake_portal(monkeypatch)
    assert client.fetch_survey_options(DMV) == [
        {"value": "2", "label": "2 (Gairan)"}, {"value": "10", "label": "10"}, {"value": "300", "label": "300"},
    ]  # the road (99901) is drawn on the map but isn't offered as a survey number


def test_portal_is_asked_only_for_this_village_and_only_for_survey_fields(monkeypatch):
    monkeypatch.setattr(client, "CHUNK", 3)
    calls = fake_portal(monkeypatch)
    client.fetch_survey_options(DMV)
    assert calls[0] == (LIS_URL, {"where": "DMV_1991='1516004'", "returnIdsOnly": "true"})
    shape_calls = [p for _, p in calls[1:]]
    assert [c["objectIds"] for c in shape_calls] == ["0,1,2", "3"]  # chunked under the server's cap
    assert {c["outFields"] for c in shape_calls} == {"Base_Syno,Descriptio,Remarks"}  # never owner/farmer fields
    assert all(url == LIS_URL for url, _ in calls)  # the older copy isn't asked when the 30 cm one has it


def test_parcel_area_corners_and_neighbours(monkeypatch):
    fake_portal(monkeypatch)
    r = client.fetch_parcel(DMV, "10")
    assert (r["village"], r["mandal"], r["district"]) == ("Kokapet", "Gandipet", "Rangareddy")
    assert r["map_version"] == "30cm"
    assert [c["label"] for c in r["corners"]] == ["P1", "P2", "P3", "P4"]  # closing point not repeated
    assert r["corners"][0] == {"label": "P1", "lat": 17.38, "lon": 78.33}
    # 0.0009° is ~99.6 m north-south and ~95.6 m east-west at 17.38°N
    assert 9450 < r["area_sq_m"] < 9600
    assert r["area_ac_gts"] == {"acres": 2, "guntas": 14}
    assert sorted(n["survey_no"] or n["kind"] for n in r["neighbours"]) == ["2", "Road"]  # 300 is too far


def test_area_subtracts_a_hole():
    outer = square(78.33, 17.38)                    # clockwise
    hole = square(78.3303, 17.3803, 0.0003)[::-1]   # anticlockwise, a ninth of the outer
    full = abs(client._signed_area_m2(outer))
    assert abs(abs(client._signed_area_m2(outer) + client._signed_area_m2(hole)) - full * 8 / 9) < 1


@pytest.mark.parametrize("dmv", ["1516004' OR '1'='1", "1516004&f=html", "౧౫౧౬౦౦౪", "9999999", "123", ""])
def test_unknown_or_malformed_village_codes_never_reach_the_portal(monkeypatch, dmv):
    calls = fake_portal(monkeypatch)
    _raises(BAD_INPUT, client.fetch_survey_options, dmv)
    _raises(BAD_INPUT, client.fetch_parcel, dmv, "10")
    assert calls == []


def test_survey_number_checks(monkeypatch):
    fake_portal(monkeypatch)
    _raises(BAD_INPUT, client.fetch_parcel, DMV, "")
    _raises(BAD_INPUT, client.fetch_parcel, DMV, "1" * 31)
    _raises(BAD_INPUT, client.fetch_parcel, DMV, "10\x00")
    _raises(NOT_FOUND, client.fetch_parcel, DMV, "99901")  # a road, not a survey number
    _raises(NOT_FOUND, client.fetch_parcel, DMV, "777")


def test_village_without_a_map_is_not_found_and_not_rescanned(monkeypatch):
    calls = fake_portal(monkeypatch, features=[])
    _raises(NOT_FOUND, client.fetch_survey_options, DMV)
    _raises(NOT_FOUND, client.fetch_survey_options, DMV)
    assert [url for url, _ in calls] == [LIS_URL, BHUNAKSHA_URL]  # each copy asked once, then cached


def test_village_missing_from_the_30cm_map_comes_from_the_older_map(monkeypatch):
    older = [{**f, "attributes": {"Parcel_num": f["attributes"]["Base_Syno"], "Descriptio": "Parcel Boundary",
                                  "Remarks": f["attributes"]["Remarks"]}} for f in FEATURES]
    calls = fake_portal(monkeypatch, features=older, has=(BHUNAKSHA_URL,))
    r = client.fetch_parcel(DMV, "10")
    assert r["map_version"] == "2.5m" and len(r["corners"]) == 4
    assert calls[1] == (BHUNAKSHA_URL, {"where": "DMV_Code='1516004'", "returnIdsOnly": "true"})
    assert {p["outFields"] for _, p in calls if "outFields" in p} == {"Parcel_num,Descriptio,Remarks"}


def test_map_with_only_a_village_outline_is_not_found(monkeypatch):
    fake_portal(monkeypatch, features=[feature("", "Parcel Boundary", "", square(78.33, 17.38))])
    _raises(NOT_FOUND, client.fetch_survey_options, DMV)


def test_identical_requests_at_once_scan_the_portal_once(monkeypatch):
    calls = fake_portal(monkeypatch, delay=0.2)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: client.fetch_parcel(DMV, "10"), range(8)))
    assert sum("returnIdsOnly" in p for _, p in calls) == 1
    assert all(r == results[0] for r in results)


@pytest.mark.parametrize("reply, message", [
    (lambda req: httpx.Response(200, text="<html>Server Error</html>"), PORTAL_DOWN),
    (lambda req: httpx.Response(200, json={"error": {"code": 500, "message": "boom"}}), PORTAL_DOWN),
    (lambda req: httpx.Response(503, text="busy"), PORTAL_DOWN),
])
def test_server_failures_become_friendly_errors(reply, message):
    with httpx.Client(transport=httpx.MockTransport(reply)) as c:
        _raises(message, client._query, c, LIS_URL, where="1=1")


def test_server_timeout_becomes_friendly_error():
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    with httpx.Client(transport=httpx.MockTransport(slow)) as c:
        _raises(PORTAL_TIMEOUT, client._query, c, LIS_URL, where="1=1")


@pytest.mark.parametrize("message, status", [(BAD_INPUT, 400), (NOT_FOUND, 404), (PORTAL_DOWN, 502)])
def test_routes_map_errors_instead_of_500(monkeypatch, message, status):
    def fail(*_):
        raise PortalError(message)

    monkeypatch.setattr(client, "fetch_survey_options", fail)
    monkeypatch.setattr(client, "fetch_parcel", fail)
    c = _app()
    assert c.get(f"/api/survey-map/survey-options/{DMV}").status_code == status
    for path in ("/api/survey-map/parcel", "/api/survey-map/pdf"):  # the PDF loads into the preview: JSON errors
        r = c.post(path, json={"dmv": DMV, "survey_no": "10"})
        assert r.status_code == status and r.json()["detail"] == message


def test_parcel_route_needs_both_fields():
    assert _app().post("/api/survey-map/parcel", json={"dmv": DMV}).status_code == 422


def test_village_search_finds_by_prefix():
    rows = _app().get("/api/survey-map/villages/search?q=kokap").json()
    assert {"district": "Rangareddy", "mandal": "Gandipet", "village": "Kokapet", "dmv": DMV} in rows


def test_at_most_two_village_searches_reach_the_portal_at_once(monkeypatch):
    from backend.core.hierarchy import _survey_map
    dmvs = [r["dmv"] for r in _survey_map()[:6]]
    live, peak, lock = [0], [0], threading.Lock()

    def fake_query(_client, url, **params):
        if "returnIdsOnly" not in params:
            return {"features": FEATURES}
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.15)
        with lock:
            live[0] -= 1
        return {"objectIds": [0]}

    monkeypatch.setattr(client, "_query", fake_query)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(client.fetch_survey_options, dmvs))
    assert peak[0] == 2 and len(results) == 6  # the other four waited their turn, none failed


def test_a_look_up_that_waits_too_long_gets_a_friendly_timeout(monkeypatch):
    fake_portal(monkeypatch)
    monkeypatch.setattr(client, "QUEUE_WAIT_SECONDS", 0.1)
    assert client._portal_slots.acquire(timeout=1) and client._portal_slots.acquire(timeout=1)
    try:
        _raises(PORTAL_TIMEOUT, client.fetch_survey_options, DMV)
    finally:
        client._portal_slots.release()
        client._portal_slots.release()


def test_broken_shapes_from_the_server_are_skipped_not_a_500(monkeypatch):
    broken = [
        {"attributes": {"Base_Syno": "5", "Descriptio": "Surveyed", "Remarks": ""}, "geometry": {"rings": [[], [[78.3, 17.3], [78.31, 17.3]]]}},
        {"attributes": {"Base_Syno": "6", "Descriptio": "Surveyed", "Remarks": ""}, "geometry": None},
        {"attributes": None, "geometry": {"rings": [square(78.32, 17.38)]}},
        *FEATURES,
    ]
    fake_portal(monkeypatch, features=broken)
    assert [o["value"] for o in client.fetch_survey_options(DMV)] == ["2", "10", "300"]
    _raises(NOT_FOUND, client.fetch_parcel, DMV, "5")
    assert client.fetch_parcel(DMV, "10")["area_sq_m"] > 0


def test_pdf_frames_the_parcel_like_the_page():
    x0, y0, x1, y1 = survey_map_pdf._frame([square(78.33, 17.38, d=0.0001)])  # a ~10 m plot
    assert round(x1 - x0) == 200 and round((x1 - x0) / (y1 - y0), 3) == round(4 / 3, 3)  # at least 200 m, 4:3
    ring = square(78.33, 17.38, d=0.009)  # ~1 km, a little taller than wide in Web Mercator metres
    x0, y0, x1, y1 = survey_map_pdf._frame([ring])
    tall = survey_map_pdf._merc(78.33, 17.389)[1] - survey_map_pdf._merc(78.33, 17.38)[1]
    assert y1 - y0 == pytest.approx(2.2 * tall) and (x1 - x0) / (y1 - y0) == pytest.approx(4 / 3)  # 0.6 of it as room each side


def test_pdf_photo_halves_its_pixels_until_esri_has_one(monkeypatch):
    sizes = []

    def esri(request):
        sizes.append(request.url.params["size"])
        if len(sizes) < 3:
            return httpx.Response(500, text="Error exporting map")
        return httpx.Response(200, content=b"\xff\xd8 a jpeg", headers={"content-type": "image/jpeg"})

    real = httpx.Client
    monkeypatch.setattr(survey_map_pdf.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(esri), **kw))
    box = (0, 0, 1000, 750)  # 1 km across: 3226 px at 0.31 m, capped at 1280
    assert survey_map_pdf._photo(box) == b"\xff\xd8 a jpeg"
    assert sizes == ["1280,960", "640,480", "320,240"]


def test_pdf_shows_the_map_details_and_corners(monkeypatch):
    fake_portal(monkeypatch)
    monkeypatch.setattr(survey_map_pdf, "_photo", lambda box: None)  # Esri unreachable: plain ground
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    r = _app().post("/api/survey-map/pdf", json={"dmv": DMV, "survey_no": "10"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="Survey-map-Kokapet-10.pdf"'
    for text in (b"(Survey Map: Survey No. 10)", b"(Kokapet village, Gandipet mandal, Rangareddy district, Telangana)",
                 b"(The satellite photo was unavailable when this PDF was made.)", b"(2 acres 14 guntas", b"(17.38045, 78.33045)",
                 b"(30 cm map, matched to sharp satellite imagery)", b"(4 corner points)", b"(P4)", b"(17.3809)", b"(2) Tj",
                 b"not a legal survey."):
        assert text in r.content, text
    assert b"(Road)" not in r.content and b"(99901)" not in r.content  # roads are drawn, not numbered
