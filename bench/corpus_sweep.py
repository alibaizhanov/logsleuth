#!/usr/bin/env python3
"""Breadth and scale sweep over real public log corpora.

Runs the scanner (not the model) over every log it is pointed at and reports
what matters for robustness: does it survive, how fast, how much memory, and is
the evidence pack sane — templates compressing, timestamps parsed, rare events
and trends found.

    python bench/corpus_sweep.py /tmp/loghub_full
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CHILD = r'''
import json, os, resource, sys, time
sys.path.insert(0, {root!r})
from logsleuth.scan import scan, build_pack, sniff_format
from logsleuth.parse import parse_line
path = sys.argv[1]
t0 = time.time()
sc = scan(path)
pack = build_pack(sc)
el = time.time() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rss = rss / (1024*1024) if sys.platform == "darwin" else rss / 1024   # bytes vs KB
# timestamp parse rate on a sample
fmt = sc["fmt"]
ok = n = 0
with open(path, errors="replace") as fh:
    for i, line in enumerate(fh):
        if i >= 5000: break
        if not line.strip(): continue
        n += 1
        if parse_line(line.rstrip("\n"), fmt)[0]: ok += 1
print(json.dumps({{
    "lines": sc["total"], "signal": sc["signal"], "templates": len(sc["templates"]),
    "seconds": round(el, 2), "rss_mb": round(rss, 1), "workers": sc["workers"],
    "fmt": fmt, "ts_rate": round(100*ok/max(n,1)),
    "rare": len(pack["changes"]), "trends": len(pack["trends"]),
    "dims": len(pack["dim_notes"]),
}}))
'''.format(root=ROOT)


def run_one(path):
    try:
        p = subprocess.run([sys.executable, "-c", CHILD, path],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"error": "TIMEOUT >30min"}
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()
        return {"error": (tail[-1] if tail else f"exit {p.returncode}")[:120]}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": "unparseable child output"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--min-mb", type=float, default=0.1)
    ap.add_argument("--out", default="corpus_sweep.json")
    args = ap.parse_args()

    files = []
    for dirpath, _, names in os.walk(args.root):
        for n in names:
            if n.endswith(".log"):
                p = os.path.join(dirpath, n)
                if os.path.getsize(p) >= args.min_mb * 1e6:
                    files.append(p)
    files.sort(key=lambda p: -os.path.getsize(p))

    print(f"{'corpus':<26}{'MB':>7}{'lines':>11}{'sec':>7}{'MB/s':>7}{'RSS':>7}"
          f"{'tpl':>7}{'compr':>7}{'ts%':>5}{'fmt':>8}{'rare':>5}{'trend':>6}")
    print("-" * 108)
    results = {}
    for p in files:
        mb = os.path.getsize(p) / 1e6
        r = run_one(p)
        name = os.path.basename(p)[:25]
        results[p] = r
        if "error" in r:
            print(f"{name:<26}{mb:7.1f}   FAILED: {r['error']}")
            continue
        compr = r["lines"] / max(r["templates"], 1)
        print(f"{name:<26}{mb:7.1f}{r['lines']:>11,}{r['seconds']:>7.1f}"
              f"{mb/max(r['seconds'],0.01):>7.1f}{r['rss_mb']:>6.0f}M{r['templates']:>7,}"
              f"{compr:>7.0f}{r['ts_rate']:>5}{r['fmt']:>8}{r['rare']:>5}{r['trends']:>6}")
    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=2)
    fails = [p for p, r in results.items() if "error" in r]
    print(f"\n{len(results)-len(fails)}/{len(results)} corpora scanned without error")


if __name__ == "__main__":
    main()
