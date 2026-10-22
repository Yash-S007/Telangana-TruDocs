"""Fetch the towns (ULBs) on the CDMA property tax portal, by district, and save them to
backend/data/cdma_towns.json for the CDMA Tax Receipt tool's "find your PTIN" search.

The list only changes when the state forms a new municipality, so it is baked into a file
instead of asking the portal every time someone opens the dropdown. Run again when that happens.

Usage:
  .venv/bin/python -m backend.scripts.scrape_cdma_towns
"""
import json
import time
from pathlib import Path

import httpx

BASE_URL = "https://cdma.cgg.gov.in/CDMA_ARBS/CDMA_PG"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_FILE = DATA_DIR / "cdma_towns.json"


def main() -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Content-Type": "application/json; charset=utf-8"}, timeout=60.0) as client:
        districts = client.post(BASE_URL + "/GetPTSearchDetails", content=json.dumps({"ApplicationID": "ptp"})).json()[0]["Circle"]
        rows = []
        for d in districts:
            time.sleep(1)  # one request a second
            towns = client.post(BASE_URL + "/GetULBData", content=json.dumps({"DistrictID": str(d["I_DSTOBJID"])})).json() or []
            rows.append({
                "district_id": d["I_DSTOBJID"],
                "district": d["VC_DSTNAME"].strip().title(),
                "towns": sorted(({"id": t["I_ULBOBJID"], "name": t["VC_ULBNAME"].strip()} for t in towns), key=lambda t: t["name"]),
            })
            print(f"  {rows[-1]['district']}: {len(towns)} towns")
    rows.sort(key=lambda r: r["district"])
    if sum(len(r["towns"]) for r in rows) < 100:
        raise SystemExit("ERROR: fewer than 100 towns — the portal's answer has changed, file not written.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} districts, {sum(len(r['towns']) for r in rows)} towns → {OUT_FILE}")


if __name__ == "__main__":
    main()
