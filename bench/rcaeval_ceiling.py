#!/usr/bin/env python3
"""Before optimizing against RCAEval, measure what is achievable at all.

Two questions no amount of prompt tuning can answer:

1. CEILING — is the injected service even visible in the logs? If a CPU stress on
   `carts` produces no `carts` log lines while `queue-master` times out loudly,
   the case is unsolvable from logs alone and belongs in the denominator honestly.
2. BASELINES — what do trivial rules score? "Name the service with the most error
   lines" needs no model. If the full pipeline cannot beat that, the model is not
   earning its 90 seconds.

No LLM calls: this reads the CSVs directly.

    python bench/rcaeval_ceiling.py /tmp/re3ss/RE3-SS
"""
import argparse
import csv
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
csv.field_size_limit(10 * 1024 * 1024)

ERR = re.compile(r"\b(error|fatal|critical|warn|exception|traceback|panic|refused|"
                 r"timeout|timed out|failed|failure|rejected|exceeded|aborted|unavailable|5\d\d)\b", re.I)


def cases(root):
    for fault in sorted(os.listdir(root)):
        fdir = os.path.join(root, fault)
        if not os.path.isdir(fdir):
            continue
        for run in sorted(os.listdir(fdir), key=lambda x: (len(x), x)):
            cdir = os.path.join(fdir, run)
            if os.path.isfile(os.path.join(cdir, "logs.csv")):
                yield fault, run, cdir


def truth_of(fault, cdir):
    rc = os.path.join(cdir, "root_cause.txt")
    if os.path.exists(rc):
        parts = open(rc, errors="replace").read(400).split(",")
        if len(parts) > 2 and parts[2].strip():
            return parts[2].strip()
    return fault.rsplit("_", 1)[0]


def inject_time(cdir):
    p = os.path.join(cdir, "inject_time.txt")
    if os.path.exists(p):
        try:
            return int(open(p).read().strip())
        except ValueError:
            return None
    return None


def analyse(cdir, inject_ts):
    """Per-service line and error counts, overall and in the 10 min after injection."""
    all_lines, err_lines = Counter(), Counter()
    post_lines, post_err = Counter(), Counter()
    with open(os.path.join(cdir, "logs.csv"), newline="", errors="replace") as fh:
        for row in csv.DictReader(fh):
            svc = (row.get("container_name") or "?").strip()
            msg = row.get("message") or ""
            is_err = bool(ERR.search(msg))
            all_lines[svc] += 1
            if is_err:
                err_lines[svc] += 1
            if inject_ts:
                try:
                    ts = int(row.get("timestamp") or 0) / 1e9
                except ValueError:
                    continue
                if inject_ts <= ts <= inject_ts + 600:
                    post_lines[svc] += 1
                    if is_err:
                        post_err[svc] += 1
    return all_lines, err_lines, post_lines, post_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    args = ap.parse_args()

    rows = []
    for fault, run, cdir in cases(args.root):
        truth = truth_of(fault, cdir)
        inj = inject_time(cdir)
        all_l, err_l, post_l, post_e = analyse(cdir, inj)

        visible = post_e.get(truth, 0) > 0 if inj else err_l.get(truth, 0) > 0
        # baselines
        b_most_err = err_l.most_common(1)[0][0] if err_l else None
        b_post_err = post_e.most_common(1)[0][0] if post_e else None
        lift = {}
        tot_e, tot_a = sum(err_l.values()), sum(all_l.values())
        for s, e in err_l.items():
            share_e, share_a = e / max(tot_e, 1), all_l.get(s, 0) / max(tot_a, 1)
            if share_a > 0:
                lift[s] = share_e / share_a
        b_lift = max(lift, key=lift.get) if lift else None
        b_rand = random.Random(hash(cdir) & 0xFFFF).choice(list(all_l)) if all_l else None

        rows.append({"case": f"{fault}/{run}", "truth": truth, "visible": visible,
                     "most_err": b_most_err, "post_err": b_post_err,
                     "lift": b_lift, "rand": b_rand,
                     "truth_err_share": round(100 * err_l.get(truth, 0) / max(tot_e, 1)),
                     "services": len(all_l)})

    n = len(rows)
    vis = sum(r["visible"] for r in rows)
    print(f"cases: {n}\n")
    print(f"CEILING — injected service produces error lines after injection: {vis}/{n} = {100*vis/n:.0f}%")
    print("           (cases where it does not are unsolvable from logs alone)\n")
    print("BASELINES (no model involved):")
    for key, label in [("most_err", "service with most error lines"),
                       ("post_err", "most error lines in 10 min after injection"),
                       ("lift", "highest error over-representation (lift)"),
                       ("rand", "random service")]:
        hit = sum(1 for r in rows if r[key] == r["truth"])
        print(f"  {label:<44}{hit:>3}/{n} = {100*hit/n:>3.0f}%")
    print(f"\nmedian share of error lines coming from the injected service: "
          f"{sorted(r['truth_err_share'] for r in rows)[n//2]}%")
    print(f"services per case: {sorted({r['services'] for r in rows})}")
    print("\nper case:")
    print(f"{'case':<16}{'truth':<13}{'visible':>8}{'most_err':<14}{'lift':<14}{'truth err %':>11}")
    for r in rows:
        print(f"{r['case']:<16}{r['truth']:<13}{str(r['visible']):>8}  {str(r['most_err']):<13}"
              f"{str(r['lift']):<14}{r['truth_err_share']:>10}%")


if __name__ == "__main__":
    main()
