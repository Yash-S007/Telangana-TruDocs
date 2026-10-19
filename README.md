# Telangana TruDocs

Real-estate document search for Telangana. Python (FastAPI) backend, React+Vite frontend.

## Status (v0, first working slice)

Working end-to-end against the live government portals:
- **GHMC Mutation Status** — fully working.
- **GHMC Property Tax Search** — fully working (circle is a required field on the portal, not optional).
- **Adangal Extract (Pahani)** — fully working, including the final search submit. (Note: survey/khata number dropdowns come back empty for most villages tried so far — that appears to be sparse data on the portal's side, not a bug on ours; the search itself correctly returns "No RoR-1B Details Found" for a number with no record, confirmed live.)
- **RERA Certificate (TG-RERA)** — fully working, no login or OTP (rerait.telangana.gov.in). Search by project name, promoter name or registration number (e.g. P02400001224); up to 50 matches per search, with the total. Each project links its official PDFs: the Registration Certificate (Form C) and, where issued, the Extension and Special 4-month extension certificates (Form F), plus the official project page. The search captcha is solved with ddddocr (first try in 26 of 26 live searches). The portal's HTTPS server omits its intermediate certificate, so `backend/scrapers/rera/emsign_ssl_ca_g1.pem` ships it (verified against the emSign root in certifi) instead of turning verification off. Results and certificates are public, cached 6 hours.

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

RERA load check (server running): `.venv/bin/python -m backend.scripts.load_test_rera --base http://localhost:8000 -n 10` fires 10 searches for different project names at once (each followed by its certificate); add `--same` for 10 identical ones.
