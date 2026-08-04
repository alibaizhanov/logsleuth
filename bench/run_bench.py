#!/usr/bin/env python3
"""Reproduce the loglens benchmark: regenerate the 10 blind scenarios and analyze each.

Usage:  python bench/run_bench.py [--model qwen3:8b]
Ground truth for grading is in bench/bench_truth.md.
"""
import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()

    subprocess.run([sys.executable, str(HERE / "gen_bench.py")], cwd=HERE, check=True)
    for i in range(1, 11):
        log = HERE / f"bench_{i:02d}.log"
        out = HERE / f"bench_report_{i:02d}.md"
        print(f"[bench] analyzing {log.name} …", flush=True)
        with open(out, "w") as fh:
            subprocess.run([sys.executable, "-m", "loglens", str(log), "--model", args.model],
                           stdout=fh, check=True)
    print(f"[bench] done — compare bench_report_NN.md against {HERE/'bench_truth.md'}")


if __name__ == "__main__":
    main()
