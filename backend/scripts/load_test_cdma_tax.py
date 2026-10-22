"""Fire N CDMA tax look-ups at the same moment at a running server, and report how each did.
The PTINs start with 00, which is no town's code, so no real property is looked up, but each
look-up still makes the portal's two round trips (receipts, then tax due). With --ptin, every
look-up is that PTIN (use one you may look up, e.g. a government building's) and each then
downloads its first official receipt PDF, which the portal takes 14-50 s to make.
Prints only counts and timings, not owner details.

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_cdma_tax --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_cdma_tax -n 10 --same   # 10 identical look-ups
  .venv/bin/python -m backend.scripts.load_test_cdma_tax -n 5 --ptin 1113300005
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


def look_up(base, ptin, receipt):
    t = time.monotonic()
    req = urllib.request.Request(f"{base}/api/cdma-tax/property", data=json.dumps({"ptin": ptin}).encode(),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            found = json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, str(json.load(e).get("detail"))[:45]
    except Exception as e:
        return 0, time.monotonic() - t, repr(e)[:60]
    note = f"{len(found['receipts'])} receipts"
    first = next((r for r in found["receipts"] if r["slno"]), None)
    if receipt and first:
        query = urllib.parse.urlencode({"ptin": ptin, "receipt_no": first["receipt_no"], "slno": first["slno"]})
        try:
            with urllib.request.urlopen(f"{base}/api/cdma-tax/receipt?{query}", timeout=300) as r:
                pdf = r.read()
            note += f", receipt {len(pdf) // 1024} KB" + ("" if pdf[:5] == b"%PDF-" else " NOT A PDF")
        except urllib.error.HTTPError as e:
            return e.code, time.monotonic() - t, "receipt failed"
    return 200, time.monotonic() - t, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--same", action="store_true")
    ap.add_argument("--ptin", help="look up this PTIN every time and download its first receipt")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    picks = [a.ptin] * a.n if a.ptin else ["0000000001"] * a.n if a.same else [f"00{i:08d}" for i in range(1, a.n + 1)]
    start = threading.Barrier(a.n)

    def fire(ptin):
        start.wait()
        return ptin, look_up(base, ptin, receipt=bool(a.ptin))

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, picks))
    wall = time.monotonic() - t0
    for ptin, (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:6.1f}s  {ptin}  {note}")
    ok = sum(1 for _, (st, _, _) in results if st in (200, 404))
    times = [s for _, (_, s, _) in results]
    print(f"\n{ok}/{a.n} answered (200/404) | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
