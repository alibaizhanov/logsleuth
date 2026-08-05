#!/usr/bin/env python3
"""Run logsleuth against RCAEval — an external, third-party RCA benchmark.

RCAEval (Pham et al., WWW'25) ships real microservice failure cases with an
annotated root-cause *service*. Each case has logs.csv (container logs) plus an
injection timestamp. We convert the logs to plain lines, hand them to logsleuth,
and check whether the report names the right service.

    python bench/rcaeval_run.py /tmp/re3ss/RE3-SS [--limit N] [--model qwen3:8b]

Honest caveats, stated up front:
- RCAEval is multi-source (metrics + traces + logs). logsleuth reads logs only,
  so cases whose signal lives purely in metrics are unwinnable for us by design.
- We score service-level localization: does the report name the injected service?
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIELD_LIMIT = 10 * 1024 * 1024
csv.field_size_limit(FIELD_LIMIT)


def case_dirs(root):
    for fault in sorted(os.listdir(root)):
        fdir = os.path.join(root, fault)
        if not os.path.isdir(fdir):
            continue
        for run in sorted(os.listdir(fdir), key=lambda x: (len(x), x)):
            cdir = os.path.join(fdir, run)
            if os.path.isfile(os.path.join(cdir, "logs.csv")):
                yield fault, run, cdir


def ground_truth(fault, cdir):
    """Injected service name — from root_cause.txt when present, else the dir name."""
    rc = os.path.join(cdir, "root_cause.txt")
    if os.path.exists(rc):
        head = open(rc, errors="replace").read(400)
        parts = head.split(",")
        if len(parts) > 2 and parts[2].strip():
            return parts[2].strip()
    return fault.rsplit("_", 1)[0]


def to_plain_log(csv_path, out_path, max_lines=200_000):
    """logs.csv -> plain log lines, keeping service identity as a field."""
    n = 0
    with open(csv_path, newline="", errors="replace") as fh, open(out_path, "w") as out:
        for row in csv.DictReader(fh):
            msg = (row.get("message") or "").replace("\n", " ").strip()
            if not msg:
                continue
            ts = row.get("timestamp") or ""
            try:                      # nanosecond epoch -> ISO
                import datetime as dt
                iso = dt.datetime.utcfromtimestamp(int(ts) / 1e9).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            except Exception:
                iso = row.get("time") or ""
            out.write(f"{iso} service={row.get('container_name','?')} "
                      f"pod={row.get('pod_name','?')} {msg}\n")
            n += 1
            if n >= max_lines:
                break
    return n


def run_logsleuth(log_path, model):
    cmd = [sys.executable, "-m", "logsleuth", log_path, "--plain", "--model", model]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return p.stdout


def names_service(report, service, services):
    """Did the report blame the right service? Look at the root-cause section only."""
    m = re.search(r"##\s*Root cause.*?(?=\n##|\Z)", report, re.S | re.I)
    section = (m.group(0) if m else report).lower()
    return service.lower() in section


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--out", default="rcaeval_results.json")
    args = ap.parse_args()

    cases = list(case_dirs(args.root))
    if args.limit:
        cases = cases[:args.limit]
    results, hits = [], 0
    for i, (fault, run, cdir) in enumerate(cases, 1):
        truth = ground_truth(fault, cdir)
        tmp = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        tmp.close()
        n = to_plain_log(os.path.join(cdir, "logs.csv"), tmp.name)
        try:
            report = run_logsleuth(tmp.name, args.model)
        except subprocess.TimeoutExpired:
            report = ""
        finally:
            os.unlink(tmp.name)
        ok = names_service(report, truth, None)
        hits += ok
        results.append({"case": f"{fault}/{run}", "truth": truth, "lines": n, "hit": ok,
                        "root_cause_excerpt": (re.search(r"##\s*Root cause.*?\n(.{0,200})",
                                                         report, re.S | re.I) or [None, ""])[1].strip()})
        print(f"[{i}/{len(cases)}] {fault}/{run:<3} truth={truth:<12} "
              f"{'HIT ' if ok else 'miss'} ({n:,} lines)", flush=True)
    with open(args.out, "w") as fh:
        json.dump({"hits": hits, "total": len(results), "cases": results}, fh, indent=2)
    print(f"\nservice localization: {hits}/{len(results)} = {100*hits/max(len(results),1):.0f}%")


if __name__ == "__main__":
    main()
