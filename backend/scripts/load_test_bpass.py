"""Fire N TG-bPASS look-ups at the same moment at a running server, and report how each did.
The file numbers are made up (000000/TEST/...), so no real application is looked up, but each
look-up still makes the portal's search round trip. With --file, every look-up is that file
number (use one you may look up) and each then downloads its first official letter.
Prints only counts and timings, not application details.

Usage (server running, e.g. on :8000):
  .venv/bin/python -m backend.scripts.load_test_bpass --base http://localhost:8000 -n 10
  .venv/bin/python -m backend.scripts.load_test_bpass -n 10 --same   # 10 identical look-ups
  .venv/bin/python -m backend.scripts.load_test_bpass -n 5 --file 123456/XXXX/0123/2025
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


def look_up(base, file_no, letter):
    t = time.monotonic()
    req = urllib.request.Request(f"{base}/api/bpass/application", data=json.dumps({"file_no": file_no}).encode(),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            found = json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, str(json.load(e).get("detail"))[:45]
    except Exception as e:
        return 0, time.monotonic() - t, repr(e)[:60]
    note = f"{found['status']}, {len(found['documents'])} letters"
    if letter and found["documents"]:
        query = urllib.parse.urlencode({"file_no": file_no, "kind": found["documents"][0]["kind"]})
        try:
            with urllib.request.urlopen(f"{base}/api/bpass/document?{query}", timeout=300) as r:
                pdf = r.read()
            note += f", letter {len(pdf) // 1024} KB" + ("" if pdf[:5] == b"%PDF-" else " NOT A PDF")
        except urllib.error.HTTPError as e:
            return e.code, time.monotonic() - t, "letter failed"
    return 200, time.monotonic() - t, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--same", action="store_true")
    ap.add_argument("--file", help="look up this file number every time and download its first letter")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    picks = ([a.file] * a.n if a.file else ["000000/TEST/0000/2025"] * a.n if a.same
             else [f"000000/TEST/{i:04d}/2025" for i in range(1, a.n + 1)])
    start = threading.Barrier(a.n)

    def fire(file_no):
        start.wait()
        return file_no, look_up(base, file_no, letter=bool(a.file))

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.n) as pool:
        results = list(pool.map(fire, picks))
    wall = time.monotonic() - t0
    for file_no, (status, secs, note) in sorted(results, key=lambda x: x[1][1]):
        print(f"{status or 'ERR':>3}  {secs:6.1f}s  {file_no}  {note}")
    ok = sum(1 for _, (st, _, _) in results if st in (200, 404))
    times = [s for _, (_, s, _) in results]
    print(f"\n{ok}/{a.n} answered (200/404) | slowest {max(times):.1f}s | median {statistics.median(times):.1f}s | wall {wall:.1f}s")


if __name__ == "__main__":
    main()
