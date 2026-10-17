"""Fire N 22-A searches at the same moment at a running server, each doing what the
website does (the category table, then every survey list it offers), and report
how each user did. Uses real villages from the pre-scraped list, so it also hits
the live government portal (politely: the client throttles its own requests).

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_prohibited_lands --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_prohibited_lands -n 10 --same   # 10 identical searches
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

DATA = Path(__file__).resolve().parent.parent / "data" / "prohibited_lands_hierarchy.json"


def post(base: str, path: str, body: dict) -> tuple:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def user(base: str, village: dict) -> tuple:
    """One person searching: categories, then all survey lists at once (like the page)."""
    loc = {k: village[k] for k in ("district_id", "mandal_id", "village_id")} | {"sro_code": ""}
    t = time.monotonic()
    try:
        status, cats = post(base, "/api/prohibited-lands/categories", loc)
        if status != 200:
            return status, time.monotonic() - t, cats.get("detail", "")
        kinds = list(cats["categories"])
        with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
            lists = list(pool.map(lambda k: post(base, "/api/prohibited-lands/survey-list", loc | {"kind": k}), kinds))
        bad = [s for s, _ in lists if s != 200]
        note = " ".join(f"{k[:3]}:{d.get('count')}" for k, (s, d) in zip(kinds, lists) if s == 200)
        return (bad[0] if bad else 200), time.monotonic() - t, note
    except Exception as e:  # connection refused, timeout: the server itself failed
        return 0, time.monotonic() - t, repr(e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10, help="users searching at the same moment")
    ap.add_argument("--same", action="store_true", help="all users search the same village")
    ap.add_argument("--seed", type=int, default=22)
    a = ap.parse_args()

    villages = [v for v in json.loads(DATA.read_text(encoding="utf-8")) if v["district_id"] != "16_1"]
    rng = random.Random(a.seed)
    picks = [rng.choice(villages)] * a.n if a.same else rng.sample(villages, a.n)
    start = threading.Barrier(a.n)  # release every user together

    def fire(v):
        start.wait()
        return v, user(a.base.rstrip("/"), v)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, picks))
    wall = time.monotonic() - t0

    for v, (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:5.1f}s  {v['village'][:24]:24} {v['district'][:20]:20} {note}")
    ok = [1 for _, (st, _, _) in results if st == 200]
    times = [s for _, (_, s, _) in results]
    print(f"\n{len(ok)}/{a.n} users got full results | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
