# Telangana TruDocs

Real-estate document search for Telangana. Python (FastAPI) backend, React+Vite frontend.

## Status (v0, first working slice)

Working end-to-end against the live government portals:
- **GHMC Mutation Status** — fully working.
- **GHMC Property Tax Search** — fully working (circle is a required field on the portal, not optional).
- **CDMA Property Tax Receipt** — fully working, no login, captcha or OTP (cdma.cgg.gov.in, every Telangana town outside GHMC). Enter a 10-digit PTIN, or pick the town and type a door number or owner name (3+ characters; up to 100 matches shown) to find it. Results show in a PDF preview with **Download PDF**, as in the Karnataka EC tool: first our own A4 PDF of the owner, door number, locality, usage, the tax due today (arrear and current, with interest) and every receipt on the portal, watermarked "Only For Information" (it reuses the look-up, so it costs the portal nothing extra); then any receipt's official PDF on request, the portal's own and untouched (seal watermark and QR code). The preview uses pdf.js (`pdfjs-dist`, as in trudocs-state's frontend shell), loaded only when a preview opens. The portal takes 14–50 s to make a receipt (over a minute when many are asked for at once), so PDFs are cached 6 hours (last 64 kept) and look-ups 5 minutes. The town list is `backend/data/cdma_towns.json`, rebuilt with `python -m backend.scripts.scrape_cdma_towns`.
- **TG-bPASS Building Permission** — fully working, no login, captcha or OTP. Enter a TG-bPASS file number to see the application's status, type, dates and place, with its official letters (the letter of approval for commencement of work, the building permit order, and any fee, revocation or show-cause letters) in the PDF preview, as on the CDMA tool. It uses the old TG-bPASS portal's public Citizen Search (backend.tsbpass.com), which still answers for the ~3.1 lakh applications filed before December 2025, when new applications moved to BuildNow (login only). The portal's own banner says it closed, so it may go away; the tool then shows a friendly message. Its application detail page is deliberately not used: it exposes applicants' Aadhaar, PAN and mobile numbers. The letters' links are signed for an hour, so they are fetched afresh; look-ups are cached 6 hours.
  - *Problems we hit while building it:*
    - **The new BuildNow portal can't be used.** TG-bPASS was replaced by BuildNow in December 2025, but BuildNow's search needs a logged-in account (mobile OTP) and Google reCAPTCHA. One shared account serving every user would get blocked and break the portal's terms (the same reason the EC tool was dropped), and reCAPTCHA is not something we automate.
    - **The old portal is officially closed.** Its own banner says it closed after 15 December 2025, yet its public search still answers, so the tool is built on it knowing it may stop.
    - **The old portal leaks personal data.** Its application detail page hands out applicants' Aadhaar, PAN, mobile, email and address to anyone, with no login. We never call it (worth reporting to the department). That page held the building facts (built-up area, floors, setbacks), so the tool shows those only inside the official letters.
    - **A search by area was dropped.** Searching a district + survey/plot/house number was planned, but the portal's town list is broken (it returns one town), its district names are stored in unusual spellings ("Hanamkonda", "Jagityal", "Medchal - Malkajgiri"…), every filter is an exact match, and the results list strangers' applications and names. For privacy and reliability the tool searches by file number only.
    - **Easy-to-miss portal traps:** an unknown search key silently means "no filter" (all 3 lakh applications, ~22 s), so only the portal's own keys are sent; the letters' links expire after an hour; a new connection is sometimes dropped and is retried once.
  - *Limitations:*
    - Only applications filed on TG-bPASS **before December 2025** (~3.1 lakh); anything newer is on BuildNow and isn't covered (the form says so up front).
    - Search by the **exact file number** only, as on the letters; no search by survey/plot number or owner name.
    - No separate built-up area / floors / setbacks block (read them in the letter), and no applicant name in the result (the letters carry it).
    - Only the letters the portal holds: some applications have none, and a rejected one shows a revocation instead of an approval.
    - If the government switches the old portal off, the tool can only say the portal isn't responding.
    - About 2 s per look-up and 3 s per letter; the portal is limited to 60 requests a minute, so 20 people searching at once wait up to ~20 s.
- **Adangal Extract (Pahani)** — fully working, including the final search submit. (Note: survey/khata number dropdowns come back empty for most villages tried so far — that appears to be sparse data on the portal's side, not a bug on ours; the search itself correctly returns "No RoR-1B Details Found" for a number with no record, confirmed live.)
- **Land Market Value (IGRS unit rates)** — fully working, no login or captcha. Outside Hyderabad: village search over a pre-scraped list (`backend/scripts/scrape_market_value_hierarchy.py`). Hyderabad: division + locality name, searched live (the portal matches the start of the name, 3+ letters). Shows only what the official page shows (land ₹/sq. yard and effective date): the portal comments out its apartment-rate column, and its apartment search returns 404.
- **Prohibited Lands (Section 22A)** — fully working, no login or captcha (IGRS `openProhibitedProperties.htm`). Village search over a pre-scraped list (`backend/scripts/scrape_prohibited_lands_hierarchy.py`); Hyderabad is division + SRO office (non-agriculture only). Shows the official PDF for each 22-A(1) category (Waqf and Endowment aren't online on the portal either) and the survey-wise list with a link to each order. A Hyderabad SRO list is ~6,000 rows and takes the portal ~30 s, so lists are cached per process for 6 hours.
- **Land Details Search (Bhu Bharati, agri land status)** — fully working, no login or OTP (Bhu Bharati `/knowLandStatus`). Two public search modes: by village + survey/khata number, or by passbook number + the last 4 digits of the owner's Aadhaar. The portal captcha is solved with ddddocr (`backend/core/captcha.py`), retried up to 8 times. Shows the portal's full 16-field record, including Land Status. Identical searches arriving together share one portal flow (single-flight); nothing is cached at rest, and the Aadhaar digits and captcha text are never logged.
- **Survey Map** — fully working, no login, captcha or OTP. Pick a village and survey number to see its boundary on a satellite photo, with neighbouring survey numbers, corner GPS points (P1, P2, …), area in acres/guntas and an "Open in Google Maps" link. Boundaries come from TGRAC's public ArcGIS server (the village maps behind tgrac.telangana.gov.in/digitallandsurvey/lis): the "30 cm" copy first, and Bhunaksha's older "2.5 m" copy for the ~1 village in 4 the 30 cm copy lacks (the page says when a result is from the older map, which can be 20–50 m off). The server takes 13–60 s to find a village's parcels, so each village is fetched once and cached (public map data), and at most 2 look-ups are sent to it at a time. The village list is `backend/data/survey_map_villages.json`, rebuilt with `python -m backend.scripts.scrape_survey_map_villages`. Satellite imagery is Esri World Imagery, loaded by the browser; check Esri's terms (or swap the provider in `SATELLITE_EXPORT` in `App.jsx`) before commercial use.
- **Village Map** — fully working, no login, captcha or OTP. Pick a village to see its whole survey map on a satellite photo: every parcel's outline and survey number (roads and streams dashed), with zoom for crowded areas, and **Download PDF** (A3: the photo, every outline and survey number, the village name, a north arrow and a "for reference only" note). It uses Survey Map's TGRAC village maps and cache, so a village opened in either tool is ready in both. The photo is stitched from Esri World Imagery tiles (same licence note as Survey Map); the PDF needs `reportlab`.
- **Hydra FTL Map (HMDA lakes)** — fully working, no login, captcha or OTP. Pick a district, mandal and village (or type a lake's name or HMDA lake ID) to list the lakes HMDA has notified there, then open a lake's official **FTL and buffer zone map** in the PDF preview with **Download PDF**, as on the TG-bPASS tool, plus its **FTL on the village survey map (cadastral)** and, where issued, the **survey numbers in the FTL and buffer zone** with their extent and ownership type. The lake's preliminary and final notification dates are shown (no final notification = the boundary is still preliminary). Source: HMDA's lakes portal (lakes.hmda.gov.in), ~3,000 lakes in 7 districts around Hyderabad; its whole list is read once and kept 6 hours, and the last 16 maps are kept 6 hours. Under the maps, **water bodies in the lake's village** from the government's encroachment survey (TGRAC's Tank Information System: each water body's size, survey number where known, status in 2023 and, inside the Outer Ring Road, in 2011, and a map link). That survey is a fixed snapshot, baked into `backend/data/hydra_water_bodies.json` and rebuilt with `python -m backend.scripts.scrape_hydra_water_bodies`.
  - *Problems we hit while building it:*
    - **The government map server's own FTL layers are broken.** TGRAC has a HYDRAA folder with `FTL_Tanks` (2014, 2023, 2025) and `Topo_Tanks`, but their layers point at nothing (no fields, no extent), and `FTL_Query` is empty. HMDA's lakes portal is the only working source of the FTL boundaries, as scanned, signed PDFs.
    - **The PDFs' file names follow no pattern** (an `_` after the lake ID or not, `/` turned into `-`, even typos such as `700-N-oo33` for `700/N/0033`), so a map can't be linked directly. The tool presses the row's button the way the page does (an ASP.NET postback, sending back the page's ~1.7 MB form state) and follows the redirect, and checks the file it is sent is for that lake and that kind of map.
    - **The encroachment survey can't be tied to an HMDA lake.** It uses neither HMDA's lake IDs nor (for 9 in 10 water bodies) names, and HMDA's list has no coordinates, so name matching linked only ~20 of ~3,000 lakes. It is shown per village instead, clearly labelled, for the user to match by survey number, size or place on the map. The two sources also spell villages differently (Thimmapalli / Thimmapally); common spelling variants are matched, and where two villages share a name in a district, only the one in the same mandal is used.
    - **The portal's list has quirks:** a few empty rows, and a few lakes listed twice (one copy without the final notification); the fuller row is kept.
  - *Limitations:*
    - Only lakes **HMDA has notified** (its area around Hyderabad, 7 districts); lakes elsewhere in Telangana aren't covered. About half have only a preliminary notification, and only those with a final notification (~1,360) have the survey-number list.
    - The maps are **scans**: the tool can't tell automatically whether a plot or GPS point is inside the FTL or buffer zone; the user reads the survey-number list or the map.
    - The water-body survey shows for **~3 in 4 lakes** (villages it has, under a matching spelling) and may list other water bodies of the same village; the status is the survey's (2023), not today's.
    - About 5 s to read HMDA's list the first time in 6 hours, then 1–3 s per map (0.1–3.5 MB); the portal is limited to 60 requests a minute.
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
at most 2 searches to the government map server at once; village map shares survey map's cache and builds each PDF once (the last 8 are kept); RERA solves its captcha per search and caches results for 6 hours; CDMA tax looks up PTINs from no town (`--ptin` for one you may look up, which also downloads its first receipt); TG-bPASS looks up made-up file numbers (`--file` for one you may look up, which also downloads its first letter); Hydra FTL opens different lakes' FTL maps (public map data), and `--same` the same lake:
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
.venv/bin/python -m backend.scripts.load_test_bpass --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_bpass --base http://localhost:8000 -n 10 --same
.venv/bin/python -m backend.scripts.load_test_hydra_ftl --base http://localhost:8000 -n 10
.venv/bin/python -m backend.scripts.load_test_hydra_ftl --base http://localhost:8000 -n 10 --same
```
