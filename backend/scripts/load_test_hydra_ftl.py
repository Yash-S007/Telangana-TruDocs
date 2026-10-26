"""Fire N Hydra FTL Map look-ups at the same moment at a running server, and report how each did.
Each look-up opens a different lake (public map data: names from HMDA's own list) and downloads
its FTL map, so each costs the portal one postback and one PDF. With --same, every look-up is the
same lake, which should cost the portal one fetch in all.

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_hydra_ftl --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_hydra_ftl -n 10 --same   # 10 identical look-ups
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


def get(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def look_up(base, key):
    t = time.monotonic()
    try:
        lake = json.loads(get(f"{base}/api/hydra-ftl/lake?{urllib.parse.urlencode({'key': key})}"))
        pdf = get(f"{base}/api/hydra-ftl/document?{urllib.parse.urlencode({'key': key, 'kind': 'ftl'})}")
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, str(json.load(e).get("detail"))[:45]
    except Exception as e:
        return 0, time.monotonic() - t, repr(e)[:60]
    note = f"{len(lake['water_bodies'])} water bodies, FTL map {len(pdf) // 1024} KB" + ("" if pdf[:5] == b"%PDF-" else " NOT A PDF")
    return 200, time.monotonic() - t, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--same", action="store_true")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    lakes = json.loads(get(f"{base}/api/hydra-ftl/lakes?q=Kunta"))["lakes"]  # also loads HMDA's list first
    keys = [lakes[0]["key"]] * a.n if a.same else [lakes[i % len(lakes)]["key"] for i in range(a.n)]
    start = threading.Barrier(a.n)

    def fire(key):
        start.wait()
        return key, look_up(base, key)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, keys))
    wall = time.monotonic() - t0
    for key, (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:6.1f}s  {key}  {note}")
    ok = sum(1 for _, (st, _, _) in results if st == 200)
    times = [s for _, (_, s, _) in results]
    print(f"\n{ok}/{a.n} answered | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
