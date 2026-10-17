"""Fire N Survey Map look-ups at the same moment at a running server and report how
each did. A village's first look-up makes the government server scan its whole
cadastral layer (~13s), so "different" villages are the hard case; identical ones
must share one scan. Picks random villages from the bundled list; prints only counts.

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_survey_map --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_survey_map -n 10 --same   # 10 identical
"""
import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VILLAGES = Path(__file__).resolve().parent.parent / "data" / "survey_map_villages.json"


def _call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
    except Exception as e:
        return 0, {"detail": repr(e)}


def look_up(base, village):
    """The user's path: survey list (the slow, cold part), then one survey's map."""
    t = time.monotonic()
    status, options = _call(f"{base}/api/survey-map/survey-options/{village['dmv']}")
    if status != 200:
        return status, time.monotonic() - t, f"survey list: {str(options.get('detail'))[:45]}"
    status, parcel = _call(f"{base}/api/survey-map/parcel", {"dmv": village["dmv"], "survey_no": options[0]["value"]})
    note = (f"{len(options)} surveys, map with {len(parcel['corners'])} corners" if status == 200
            else f"map: {str(parcel.get('detail'))[:45]}")
    return status, time.monotonic() - t, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--same", action="store_true")
    ap.add_argument("--seed", type=int, default=None, help="repeat the same random villages")
    a = ap.parse_args()
    base = a.base.rstrip("/")

    villages = json.loads(VILLAGES.read_text(encoding="utf-8"))
    rng = random.Random(a.seed)
    picks = [rng.choice(villages)] * a.n if a.same else rng.sample(villages, a.n)
    start = threading.Barrier(a.n)

    def fire(v):
        start.wait()
        return v, look_up(base, v)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, picks))
    wall = time.monotonic() - t0

    for v, (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:6.1f}s  {v['village'][:18]:18} {v['district'][:14]:14} {note}")
    ok = sum(1 for _, (st, _, _) in results if st in (200, 404))
    times = [s for _, (_, s, _) in results]
    print(f"\n{ok}/{a.n} answered (200/404) | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
