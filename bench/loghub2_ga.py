#!/usr/bin/env python3
"""Grouping accuracy against Loghub-2.0 — the large-scale successor to LogHub.

The ISSTA'24 evaluation ("How Far Are We?") showed the original 2k-line LogHub
overstates every parser: on full datasets averaging 3.6M lines, accuracy drops
sharply and most parsers cannot finish at all. Loghub-2.0 is what the field now
reports against, so it is the number that means something.

    # download the 14 zips from https://zenodo.org/record/8275861 into /tmp/loghub2
    python bench/loghub2_ga.py /tmp/loghub2

GA = share of lines whose group exactly matches the human-annotated group. A
group counts only if it matches a truth group *exactly* — no partial credit, so
one stray line spoils the whole cluster. That is the standard definition and the
reason it is a demanding metric.

Two deviations from the 2k harness, both deliberate:
  - templates are mined from a bounded sample and then frozen, which is what
    scan.py does in production. Training on all 3.6M lines would measure a
    program we do not ship.
  - throughput is reported, because the ISSTA'24 finding was that most parsers
    are too slow to use at this scale, and that is worth knowing about ours.
"""
import argparse
import csv
import os
import resource
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logsleuth.drain import Drain  # noqa: E402
from logsleuth.scan import TRAIN_LINES  # noqa: E402

csv.field_size_limit(10 * 1024 * 1024)

SYSTEMS = ["Apache", "BGL", "HDFS", "Hadoop", "HealthApp", "HPC", "Linux", "Mac",
           "OpenSSH", "OpenStack", "Proxifier", "Spark", "Thunderbird", "Zookeeper"]


def rows_of(path, limit=0):
    """Stream (Content, EventId) pairs; the CSVs are far too big to hold twice."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh)):
            if limit and n >= limit:
                return
            c = row.get("Content") or ""
            if c:
                yield c, row.get("EventId")


def ga(root, system, limit=0, train_lines=TRAIN_LINES):
    path = os.path.join(root, system, f"{system}_full.log_structured.csv")
    if not os.path.exists(path):
        return None

    t0 = time.monotonic()
    miner = Drain()
    for i, (c, _) in enumerate(rows_of(path, limit)):
        if i >= train_lines:
            break
        miner.train(c)
    miner.seal()      # same freeze the scanner performs via Drain.state()
    train_s = time.monotonic() - t0

    # Assign every line, keeping only group memberships — never the lines.
    ours, truth = defaultdict(list), defaultdict(list)
    n = 0
    for c, e in rows_of(path, limit):
        ours[miner.match(c)].append(n)
        truth[e].append(n)
        n += 1
    if not n:
        return None
    total_s = time.monotonic() - t0

    # A group scores only if it is exactly one truth group. Every member of a
    # truth group is mapped to the *same* list object, so identity comparison
    # settles it in one pass. Rebuilding a tuple per member instead is quadratic
    # and does not finish at all on the million-line groups in BGL or Spark.
    truth_of = {}
    for g in truth.values():
        for i in g:
            truth_of[i] = g
    correct = 0
    for g in ours.values():
        t = truth_of.get(g[0])
        if t is not None and len(t) == len(g) and all(truth_of.get(i) is t for i in g):
            correct += len(g)
    return {"ga": round(100 * correct / n), "lines": n, "truth": len(truth),
            "ours": len(ours), "sec": total_s, "train_s": train_s,
            "lps": n / max(total_s, 1e-9)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=0, help="cap lines per system (smoke test)")
    ap.add_argument("--only", help="comma-separated subset of systems")
    args = ap.parse_args()

    systems = args.only.split(",") if args.only else SYSTEMS
    print(f"{'system':<14}{'GA%':>5}{'lines':>12}{'human':>8}{'ours':>7}{'sec':>8}{'lines/s':>11}")
    scores, total_lines, total_sec = [], 0, 0.0
    for s in systems:
        r = ga(args.root, s, args.limit)
        if r is None:
            print(f"{s:<14}{'-- not downloaded --':>40}")
            continue
        scores.append(r["ga"])
        total_lines += r["lines"]
        total_sec += r["sec"]
        print(f"{s:<14}{r['ga']:>5}{r['lines']:>12,}{r['truth']:>8}{r['ours']:>7}"
              f"{r['sec']:>8.1f}{r['lps']:>11,.0f}", flush=True)

    if scores:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
        print(f"\naverage GA: {sum(scores)/len(scores):.1f}%  over {len(scores)} systems")
        print(f"{total_lines:,} lines in {total_sec/60:.1f} min "
              f"({total_lines/max(total_sec,1e-9):,.0f} lines/s), peak RSS {rss:.0f} MB")


if __name__ == "__main__":
    main()
