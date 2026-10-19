"""Fire N RERA searches at the same moment at a running server, then fetch each first
result's certificate, and report how each did. Every search solves the portal's captcha
(ddddocr), so this is a realistic load check. Prints only counts, not project details.

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_rera --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_rera -n 10 --same   # 10 identical searches
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

# Common words in Telangana project names; each matches a handful to a few hundred projects.
WORDS = ["AVASA", "HOMES", "RESIDENCY", "ENCLAVE", "TOWERS", "VILLAS", "HEIGHTS", "MEADOWS", "GREENS", "PARADISE",
         "NEST", "COUNTY", "PRIDE", "ELITE", "GARDENS", "PARK", "VISTA", "SPRINGS", "AVENUE", "ICON"]


def look_up(base, word):
    t = time.monotonic()
    req = urllib.request.Request(f"{base}/api/rera/search", data=json.dumps({"project_name": word}).encode(),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            found = json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, str(json.load(e).get("detail"))[:45]
    except Exception as e:
        return 0, time.monotonic() - t, repr(e)[:60]
    cert = found["projects"][0]["certificates"][0]
    try:
        with urllib.request.urlopen(f"{base}/api/rera/certificate?{urllib.parse.urlencode(cert)}", timeout=300) as r:
            pdf = r.read()
        note = f"{found['shown']}/{found['total']} projects, certificate {len(pdf) // 1024} KB" + ("" if pdf[:5] == b"%PDF-" else " NOT A PDF")
        return 200, time.monotonic() - t, note
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, "certificate failed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--same", action="store_true")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    picks = [WORDS[0]] * a.n if a.same else (WORDS * a.n)[:a.n]
    start = threading.Barrier(a.n)

    def fire(word):
        start.wait()
        return word, look_up(base, word)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, picks))
    wall = time.monotonic() - t0
    for word, (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:6.1f}s  {word:10} {note}")
    ok = sum(1 for _, (st, _, _) in results if st in (200, 404))
    times = [s for _, (_, s, _) in results]
    print(f"\n{ok}/{a.n} answered (200/404) | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
