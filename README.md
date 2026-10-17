# Telangana TruDocs

Real-estate document search for Telangana. Python (FastAPI) backend, React+Vite frontend.

## Status (v0, first working slice)

Working end-to-end against the live government portals:
- **GHMC Mutation Status** — fully working.
- **GHMC Property Tax Search** — fully working (circle is a required field on the portal, not optional).
- **Adangal Extract (Pahani)** — fully working, including the final search submit. (Note: survey/khata number dropdowns come back empty for most villages tried so far — that appears to be sparse data on the portal's side, not a bug on ours; the search itself correctly returns "No RoR-1B Details Found" for a number with no record, confirmed live.)
- **Land Market Value (IGRS unit rates)** — fully working, no login or captcha. Outside Hyderabad: village search over a pre-scraped list (`backend/scripts/scrape_market_value_hierarchy.py`). Hyderabad: division + locality name, searched live (the portal matches the start of the name, 3+ letters). Shows only what the official page shows (land ₹/sq. yard and effective date): the portal comments out its apartment-rate column, and its apartment search returns 404.
- **Prohibited Lands (Section 22A)** — fully working, no login or captcha (IGRS `openProhibitedProperties.htm`). Village search over a pre-scraped list (`backend/scripts/scrape_prohibited_lands_hierarchy.py`); Hyderabad is division + SRO office (non-agriculture only). Shows the official PDF for each 22-A(1) category (Waqf and Endowment aren't online on the portal either) and the survey-wise list with a link to each order. A Hyderabad SRO list is ~6,000 rows and takes the portal ~30 s, so lists are cached per process for 6 hours.

Not yet built: Pattadar Passbook (its known URL currently 404s on the live portal — needs re-verification), Bhu Bharati EC (no confirmed working URL found yet), TG-IGRS Encumbrance Certificate (confirmed to require citizen login + OTP — blocked on that decision).

## Run locally

Backend:
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn backend.main:app --reload
```

Frontend (separate terminal, dev mode with hot reload, proxies /api to :8000):
```
cd frontend
npm install
npm run dev
```

Or build the frontend once and let the backend serve it as one process:
```
cd frontend && npm run build && cd ..
.venv/bin/uvicorn backend.main:app
```

Tests (parsers and error mapping, no network):
```
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

Load test (server running): fires N searches at the same moment at the live portal (the
client throttles itself to 2 portal requests a second, and repeats are cached for 6 hours):
```
.venv/bin/python -m backend.scripts.load_test_market_value --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_market_value --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_prohibited_lands --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_prohibited_lands --base http://localhost:8000 -n 10 --same
```
