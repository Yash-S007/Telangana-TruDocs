"""Village Map: a whole village's survey map.

The survey-number outlines are the same public TGRAC village maps the Survey Map tool reads
(fetched, cached and rate-limited by its client), so a village opened in either tool is ready
in both.
"""
from backend.core.hierarchy import survey_map_village
from backend.scrapers.survey_map import client as survey_map


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
