"""Bulk-scrape District → Mandal → Village from the IGRS 22-A Prohibited Properties search.

Saves backend/data/prohibited_lands_hierarchy.json — a flat list of records:
  {"district_id","district","mandal_id","mandal","village_id","village"}

Hyderabad (16_1) has no mandals on this portal: its three divisions are listed as
villages under mandal "00" (the SRO office is picked live, per division).

Resumable: progress tracked in backend/data/_prohibited_lands_scrape_progress.json.
The client's own throttle keeps it to one request per second.

Usage:
  .venv/bin/python -m backend.scripts.scrape_prohibited_lands_hierarchy
"""
import json
import time
from pathlib import Path

from backend.core.errors import PortalError
from backend.scrapers.prohibited_lands import client as pl

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_FILE = DATA_DIR / "prohibited_lands_hierarchy.json"
PROGRESS_FILE = DATA_DIR / "_prohibited_lands_scrape_progress.json"


def _retry(fn, *args, retries: int = 3):
    for attempt in range(retries):
        try:
            return fn(*args)
        except PortalError as exc:
            wait = 5 * (attempt + 1)
            print(f"  WARN: {fn.__name__}{args} attempt {attempt + 1} failed ({exc.detail}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"{fn.__name__}{args} failed after {retries} attempts")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    records = json.loads(OUT_FILE.read_text(encoding="utf-8")) if OUT_FILE.exists() else []
    done = set(json.loads(PROGRESS_FILE.read_text())) if PROGRESS_FILE.exists() else set()
    seen = {(r["district_id"], r["mandal_id"], r["village_id"]) for r in records}

    districts = _retry(pl.fetch_districts)
    print(f"Found {len(districts)} districts.")

    for di, district in enumerate(districts, 1):
        d_id, d_name = district["value"], district["label"]
        if d_id == pl.HYDERABAD:
            mandals = [{"value": pl.HYDERABAD_MANDAL, "label": d_name}]
        else:
            mandals = _retry(pl.fetch_mandals, d_id)
        print(f"\n[{di}/{len(districts)}] {d_name} (id={d_id}): {len(mandals)} mandals")

        for mandal in mandals:
            m_id, m_name = mandal["value"], mandal["label"]
            key = f"{d_id}:{m_id}"
            if key in done:
                continue

            villages = _retry(pl.fetch_villages, d_id, m_id)
            print(f"  {m_name}: {len(villages)} villages")
            for village in villages:
                if (d_id, m_id, village["value"]) not in seen:
                    records.append({
                        "district_id": d_id,
                        "district": d_name,
                        "mandal_id": m_id,
                        "mandal": m_name,
                        "village_id": village["value"],
                        "village": village["label"],
                    })
                    seen.add((d_id, m_id, village["value"]))

            done.add(key)
            PROGRESS_FILE.write_text(json.dumps(sorted(done)))
            OUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {len(records)} total village records → {OUT_FILE}")
    PROGRESS_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
