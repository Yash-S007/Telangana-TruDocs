"""Fetch the government's survey of water bodies in the HMDA area (TGRAC's Tank Information
System: every lake and tank seen on satellite images, with whether it was live or encroached in
2011 and in 2023) and save it to backend/data/hydra_water_bodies.json for the Hydra FTL Map tool.

The survey is a fixed snapshot, so it is baked into a file instead of asking TGRAC's slow
server on every search. Run again if TGRAC publishes a newer survey.

Usage:
  .venv/bin/python -m backend.scripts.scrape_hydra_water_bodies
"""
import json
import re
import time
from pathlib import Path

import httpx

LAYER = "https://tgrac.telangana.gov.in/arcgis/rest/services/TIS_Folder/HMDA_ORR_GHMC_Water_Bodies_Query/MapServer/1/query"
FIELDS = "FID,District,Mandal,Village,WB_Name,WBA_Acres,Base_Syno,WBS_2011,WBS_2023,Lattitude,Longitude"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PAGE = 1000  # the server's cap on one reply

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_FILE = DATA_DIR / "hydra_water_bodies.json"

# The survey's words for a water body's state, in plain English.
STATUS = {
    "Live": "Live",
    "Dead": "Dead (no water)",
    "Partially Encroached": "Partly encroached",
    "Partially Encroached - Built-up": "Partly encroached by buildings",
    "Partially Encroached - Agriculture": "Partly encroached by farming",
    "Totally Encroached": "Fully encroached",
    "Totally Encroached - Built-up": "Fully encroached by buildings",
    "Totally Encroached - Agriculture": "Fully encroached by farming",
}


def status(value: str) -> str:
    value = re.sub(r"Encroached\s*-\s*", "Encroached - ", (value or "").strip())  # "Encroached- Agriculture" too
    if value and value not in STATUS:
        raise SystemExit(f"ERROR: unknown status {value!r} — add it to STATUS, file not written.")
    return STATUS.get(value, "")


def degrees(dms: str):
    """'78° 30\\' 54.915" E' → 78.51525; None if it isn't a coordinate."""
    m = re.fullmatch(r"\s*(\d+)°\s*(\d+)'\s*([\d.]+)\"\s*[NE]\s*", dms or "")
    return round(int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600, 5) if m else None


def main() -> None:
    rows = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120.0) as client:
        while True:
            time.sleep(1)  # one request a second
            data = client.get(LAYER, params={"f": "json", "where": f"FID>={len(rows)} AND FID<{len(rows) + PAGE}",
                                             "outFields": FIELDS, "returnGeometry": "false", "orderByFields": "FID"}).json()
            if "error" in data:
                raise SystemExit(f"ERROR: TGRAC said {data['error']}, file not written.")
            features = [f["attributes"] for f in data.get("features", [])]
            rows += features
            print(f"  {len(rows)} water bodies")
            if len(features) < PAGE:
                break
    out = []
    for a in rows:
        lat, lon = degrees(a["Lattitude"]), degrees(a["Longitude"])
        out.append({
            "district": a["District"].strip(), "mandal": a["Mandal"].strip(), "village": a["Village"].strip(),
            "name": a["WB_Name"].strip(), "survey_no": a["Base_Syno"].strip(), "acres": round(a["WBA_Acres"] or 0, 2),
            "status_2011": status(a["WBS_2011"]), "status_2023": status(a["WBS_2023"]),
            "lat": lat if lat and 15 < lat < 20 else None, "lon": lon if lon and 76 < lon < 82 else None,  # inside Telangana
        })
    if len(out) < 3000:
        raise SystemExit("ERROR: fewer than 3,000 water bodies — TGRAC's answer has changed, file not written.")
    out.sort(key=lambda w: (w["district"], w["mandal"], w["village"], -w["acres"]))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # One water body per line, so a re-run shows up as a readable diff.
    OUT_FILE.write_text("[\n" + ",\n".join(json.dumps(w, ensure_ascii=False) for w in out) + "\n]\n", encoding="utf-8")
    print(f"Saved {len(out)} water bodies in {len({(w['district'], w['village']) for w in out})} villages → {OUT_FILE}")


if __name__ == "__main__":
    main()
