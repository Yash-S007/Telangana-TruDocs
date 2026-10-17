"""Scrape the District → Mandal → Village list for the Survey Map tool.

Source: TGRAC's public ArcGIS village-boundary layer (the one behind the public viewer at
tgrac.telangana.gov.in/digitallandsurvey/lis/Default.aspx). Attributes only, no shapes.

Saves backend/data/survey_map_villages.json — a flat list of records:
  {"district","mandal","village","dmv"}   (dmv = the 1991 census village code that the
                                            cadastral layer is keyed by)

Takes a few seconds: IDs in one call, then attributes in chunks of 1000 (the server's cap).

Usage:
  .venv/bin/python -m backend.scripts.scrape_survey_map_villages
"""
import json
import re
import time
from pathlib import Path

import httpx

VILLAGES_URL = (
    "https://tgrac.telangana.gov.in/arcgis/rest/services/LIS_Folder/"
    "LandInformationSystem_Admin/MapServer/2/query"
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
RATE_SECONDS = 0.8  # conservative — government server
CHUNK = 1000

OUT_FILE = Path(__file__).resolve().parent.parent / "data" / "survey_map_villages.json"


def _query(client: httpx.Client, **params) -> dict:
    for attempt in range(3):
        try:
            time.sleep(RATE_SECONDS)
            resp = client.post(VILLAGES_URL, data={**params, "f": "json"}, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data
        except Exception as exc:
            wait = 5 * (attempt + 1)
            print(f"  WARN: attempt {attempt + 1} failed ({exc}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError("village layer query failed after 3 attempts")


def _clean(name: str) -> str:
    # The layer writes "Karimnagar_Rural", "BhadradriKothagudem" and "Ambajipet1712014";
    # show them as words without the glued-on code.
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", (name or "").replace("_", " "))
    name = re.sub(r"(?<=[A-Za-z)])-?\d{5,}$", "", name)
    return re.sub(r"\s+", " ", name).strip()


def main() -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        ids = sorted(_query(client, where="1=1", returnIdsOnly="true")["objectIds"])
        print(f"{len(ids)} villages on the server")
        records, seen, no_code, repeats = [], set(), 0, 0
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i:i + CHUNK]
            data = _query(client, objectIds=",".join(map(str, chunk)),
                          outFields="District,Mandal,Village,DMV_1991", returnGeometry="false")
            for f in data["features"]:
                a = f["attributes"]
                dmv = (a.get("DMV_1991") or "").strip()
                # 9999999 ("Forest"), 88888888 ("Nizamsagar" reservoir) are placeholders, not villages.
                if not dmv.isdigit() or re.fullmatch(r"(\d)\1+", dmv):
                    no_code += 1
                    continue
                if dmv in seen:  # a village drawn as several boundary pieces
                    repeats += 1
                    continue
                seen.add(dmv)
                records.append({"district": _clean(a["District"]), "mandal": _clean(a["Mandal"]),
                                "village": _clean(a["Village"]), "dmv": dmv})
            print(f"  {min(i + CHUNK, len(ids))}/{len(ids)}")
    records.sort(key=lambda r: (r["district"], r["mandal"], r["village"]))
    OUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} villages ({len({r['district'] for r in records})} districts) → {OUT_FILE}"
          f" | skipped {no_code} without a real village code, {repeats} extra pieces of a village")


if __name__ == "__main__":
    main()
