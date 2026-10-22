# Telangana TruDocs

Real-estate document search for Telangana. Python (FastAPI) backend, React+Vite frontend.

## Status (v0, first working slice)

Working end-to-end against the live government portals:
- **GHMC Mutation Status** — fully working.
- **GHMC Property Tax Search** — fully working (circle is a required field on the portal, not optional).
- **CDMA Property Tax Receipt** — fully working, no login, captcha or OTP (cdma.cgg.gov.in, every Telangana town outside GHMC). Enter a 10-digit PTIN, or pick the town and type a door number or owner name (3+ characters; up to 100 matches shown) to find it. Shows the owner, door number, locality, usage, the tax due today (arrear and current, with interest) and every receipt on the portal; each receipt opens as the portal's own official PDF (seal watermark and QR code). The portal takes 14–50 s to make a receipt (over a minute when many are asked for at once), so PDFs are cached 6 hours (last 64 kept) and look-ups 5 minutes. The town list is `backend/data/cdma_towns.json`, rebuilt with `python -m backend.scripts.scrape_cdma_towns`.
- **Adangal Extract (Pahani)** — fully working, including the final search submit. (Note: survey/khata number dropdowns come back empty for most villages tried so far — that appears to be sparse data on the portal's side, not a bug on ours; the search itself correctly returns "No RoR-1B Details Found" for a number with no record, confirmed live.)
- **Land Market Value (IGRS unit rates)** — fully working, no login or captcha. Outside Hyderabad: village search over a pre-scraped list (`backend/scripts/scrape_market_value_hierarchy.py`). Hyderabad: division + locality name, searched live (the portal matches the start of the name, 3+ letters). Shows only what the official page shows (land ₹/sq. yard and effective date): the portal comments out its apartment-rate column, and its apartment search returns 404.
- **Prohibited Lands (Section 22A)** — fully working, no login or captcha (IGRS `openProhibitedProperties.htm`). Village search over a pre-scraped list (`backend/scripts/scrape_prohibited_lands_hierarchy.py`); Hyderabad is division + SRO office (non-agriculture only). Shows the official PDF for each 22-A(1) category (Waqf and Endowment aren't online on the portal either) and the survey-wise list with a link to each order. A Hyderabad SRO list is ~6,000 rows and takes the portal ~30 s, so lists are cached per process for 6 hours.
- **Land Details Search (Bhu Bharati, agri land status)** — fully working, no login or OTP (Bhu Bharati `/knowLandStatus`). Two public search modes: by village + survey/khata number, or by passbook number + the last 4 digits of the owner's Aadhaar. The portal captcha is solved with ddddocr (`backend/core/captcha.py`), retried up to 8 times. Shows the portal's full 16-field record, including Land Status. Identical searches arriving together share one portal flow (single-flight); nothing is cached at rest, and the Aadhaar digits and captcha text are never logged.
- **Survey Map** — fully working, no login, captcha or OTP. Pick a village and survey number to see its boundary on a satellite photo, with neighbouring survey numbers, corner GPS points (P1, P2, …), area in acres/guntas and an "Open in Google Maps" link. Boundaries come from TGRAC's public ArcGIS server (the village maps behind tgrac.telangana.gov.in/digitallandsurvey/lis): the "30 cm" copy first, and Bhunaksha's older "2.5 m" copy for the ~1 village in 4 the 30 cm copy lacks (the page says when a result is from the older map, which can be 20–50 m off). The server takes 13–60 s to find a village's parcels, so each village is fetched once and cached (public map data), and at most 2 look-ups are sent to it at a time. The village list is `backend/data/survey_map_villages.json`, rebuilt with `python -m backend.scripts.scrape_survey_map_villages`. Satellite imagery is Esri World Imagery, loaded by the browser; check Esri's terms (or swap the provider in `SATELLITE_EXPORT` in `App.jsx`) before commercial use.
- **Village Map** — fully working, no login, captcha or OTP. Pick a village to see its whole survey map on a satellite photo: every parcel's outline and survey number (roads and streams dashed), with zoom for crowded areas, and **Download PDF** (A3: the photo, every outline and survey number, the village name, a north arrow and a "for reference only" note). It uses Survey Map's TGRAC village maps and cache, so a village opened in either tool is ready in both. The photo is stitched from Esri World Imagery tiles (same licence note as Survey Map); the PDF needs `reportlab`.
- **RERA Certificate (TG-RERA)** — fully working, no login or OTP (rerait.telangana.gov.in). Search by project name, promoter name or registration number (e.g. P02400001224); up to 50 matches per search, with the total. Each project links its official PDFs: the Registration Certificate (Form C) and, where issued, the Extension and Special 4-month extension certificates (Form F), plus the official project page. The search captcha is solved with ddddocr (first try in 26 of 26 live searches). The portal's HTTPS server omits its intermediate certificate, so `backend/scrapers/rera/emsign_ssl_ca_g1.pem` ships it (verified against the emSign root in certifi) instead of turning verification off. Results and certificates are public, cached 6 hours.

Not yet built: Bhu Bharati EC (no confirmed working URL found yet), TG-IGRS Encumbrance Certificate (confirmed to require citizen login + OTP — blocked on that decision).

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

Tests (parsers, validation, error mapping and single-flight — no network, synthetic data):
```
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

Load tests (server running) fire N searches at the same moment at the live portals. Market value and prohibited
lands throttle themselves to 2 portal requests a second and cache repeats for 6 hours; land details solves the
captcha for each search, and identical searches share one flow; survey map caches each village and sends
at most 2 searches to the government map server at once; village map shares survey map's cache and builds each PDF once (the last 8 are kept); RERA solves its captcha per search and caches results for 6 hours; CDMA tax looks up PTINs from no town (`--ptin` for one you may look up, which also downloads its first receipt):
```
.venv/bin/python -m backend.scripts.load_test_market_value --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_market_value --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_prohibited_lands --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_prohibited_lands --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_land_details --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_land_details --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_survey_map --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_survey_map --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_village_map --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_village_map --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_rera --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_rera --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_cdma_tax --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_cdma_tax --base http://localhost:8000 -n 10 --same
```
