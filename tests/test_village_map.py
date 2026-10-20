"""Village Map: the whole-village data for drawing. Synthetic shapes only; the village code is
a real one from our list (codes are public, not personal)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import BAD_INPUT, NOT_FOUND, PortalError
from backend.routers import village_map as village_map_router
from backend.scrapers.survey_map import client as survey_map

DMV = "1516004"  # Kokapet, Gandipet, Rangareddy


def square(x0, y0, d=0.0009):
    return [[x0, y0], [x0, y0 + d], [x0 + d, y0 + d], [x0 + d, y0], [x0, y0]]


PARCELS = (
    {"survey_no": "163", "kind": "Surveyed", "remarks": "Patta", "rings": [square(78.3201234567, 17.4001234567)]},
    {"survey_no": "164", "kind": "Surveyed", "remarks": "", "rings": [square(78.3211, 17.4001)]},
    {"survey_no": "99901", "kind": "UnSurveyed-Road", "remarks": "", "rings": [square(78.3221, 17.4001, 0.0003)]},
)


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


def _app():
    app = FastAPI()
    app.include_router(village_map_router.router)
    return TestClient(app)


def test_map_has_every_parcel_and_numbers_only_on_surveys(portal):
    data = _app().get(f"/api/village-map/map/{DMV}").json()
    assert (data["village"], data["mandal"], data["district"], data["map_version"]) == ("Kokapet", "Gandipet", "Rangareddy", "30cm")
    assert [p["survey_no"] for p in data["parcels"]] == ["163", "164", ""]  # roads and streams have no number
    assert [p["kind"] for p in data["parcels"]] == ["Patta", "Surveyed", "UnSurveyed-Road"]
    assert data["parcels"][0]["rings"][0][0] == [78.320123, 17.400123]  # ~0.1 m is plenty to draw


def test_unknown_village_codes_never_reach_the_portal(monkeypatch):
    monkeypatch.setattr(survey_map, "_village_parcels", lambda dmv: pytest.fail("portal called"))
    for dmv in ("123", "abc", "1516004'--"):
        resp = _app().get(f"/api/village-map/map/{dmv}")
        assert resp.status_code == 400 and resp.json()["detail"] == BAD_INPUT


def test_village_without_a_map_is_a_friendly_not_found(portal):
    resp = _app().get("/api/village-map/map/1903030")
    assert resp.status_code == 404 and resp.json()["detail"] == NOT_FOUND
