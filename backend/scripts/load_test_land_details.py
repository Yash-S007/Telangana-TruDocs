"""Fire N land-details (survey) searches at the same moment at a running server and
report how each did. Each search solves the portal captcha (ddddocr) and hits the
live portal, so this is a realistic load check. Uses a real village's survey/khata
numbers; no personal data is printed.

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_land_details --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_land_details -n 10 --same   # 10 identical searches
"""
import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Kokapet, Gandipet, Rangareddy — a dense village with many survey numbers.
VILLAGE = {"district_id": "5", "mandal_id": "83", "village_id": "507004"}


def _get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def search(base, survey_no, khata_id):
    body = json.dumps({**VILLAGE, "survey_no": survey_no, "khata_id": khata_id}).encode()
    req = urllib.request.Request(f"{base}/api/pattadar/search", data=body, headers={"content-type": "application/json"})
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.load(r)
            return r.status, time.monotonic() - t, f"found={d.get('found')}, {len(d.get('raw_fields', {}))} fields"
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, json.load(e).get("detail", "")[:50]
    except Exception as e:
        return 0, time.monotonic() - t, repr(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--same", action="store_true")
    a = ap.parse_args()
    base = a.base.rstrip("/")

    surveys = _get(f"{base}/api/pattadar/survey-options/{VILLAGE['village_id']}")
    pairs = []
    for s in surveys:
        khatas = _get(f"{base}/api/pattadar/khata-options/{VILLAGE['village_id']}?survey_no={urllib.parse.quote(s['value'])}")
        if khatas:
            pairs.append((s["value"], khatas[0]["value"]))
        if not a.same and len(pairs) >= a.n:
            break
        if a.same and pairs:
            break
    if not pairs:
        print("could not find any survey/khata pairs to test"); return
    picks = [pairs[0]] * a.n if a.same else (pairs * a.n)[:a.n]

    start = threading.Barrier(a.n)

    def fire(p):
        start.wait()
        return p, search(base, *p)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, picks))
    wall = time.monotonic() - t0

    for (sv, kh), (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:6.1f}s  survey {sv[:16]:16} khata {kh[:8]:8} {note}")
    ok = sum(1 for _, (st, _, _) in results if st in (200, 404))
    times = [s for _, (_, s, _) in results]
    print(f"\n{ok}/{a.n} answered (200/404) | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
