#!/usr/bin/env python3
"""Grouping-accuracy benchmark against LogHub (real logs, human-annotated templates).

    git clone --depth 1 https://github.com/logpai/loghub /tmp/loghub
    python bench/loghub_ga.py /tmp/loghub

GA = share of lines whose group exactly matches the human-annotated group.
"""
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logsleuth.drain import Drain  # noqa: E402

SYSTEMS = ["HDFS", "Linux", "OpenStack", "Android", "Apache", "BGL", "Hadoop", "Spark",
           "Zookeeper", "OpenSSH", "HealthApp", "Proxifier", "Windows", "Mac", "HPC", "Thunderbird"]


def ga(root, system):
    path = os.path.join(root, system, f"{system}_2k.log_structured.csv")
    if not os.path.exists(path):
        return None
    contents, eids = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            c = row.get("Content") or ""
            if c:
                contents.append(c)
                eids.append(row.get("EventId"))
    miner = Drain()
    for c in contents:
        miner.train(c)
    ours, truth = defaultdict(list), defaultdict(list)
    for i, (c, e) in enumerate(zip(contents, eids)):
        ours[miner.match(c)].append(i)
        truth[e].append(i)
    truth_of = {}
    for g in truth.values():
        for i in g:
            truth_of[i] = tuple(g)
    correct = sum(len(g) for g in ours.values() if all(truth_of.get(i) == tuple(g) for i in g))
    return round(100 * correct / len(contents)), len(truth), len(ours)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "/tmp/loghub"
    scores = []
    print(f"{'system':<12} {'GA%':>5} {'human':>7} {'ours':>6}")
    for s in SYSTEMS:
        r = ga(root, s)
        if r:
            g, h, o = r
            scores.append(g)
            print(f"{s:<12} {g:>5} {h:>7} {o:>6}")
    if scores:
        print(f"\naverage GA: {sum(scores)/len(scores):.1f}%")


if __name__ == "__main__":
    main()
