#!/usr/bin/env python3
"""Adversarial inputs: logsleuth must never show a traceback.

The input space is unbounded, so the primary defence is the catch-all in
cli.cli(). These cases are the ones we know are real, kept as a regression.

    python bench/test_robustness.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_cases(d):
    cases = []

    p = os.path.join(d, "empty.log")
    open(p, "w").close()
    cases.append((p, "empty file"))

    p = os.path.join(d, "one.log")
    open(p, "w").write("2026-08-04T00:00:00Z INFO only one line\n")
    cases.append((p, "single line"))

    p = os.path.join(d, "giant.log")                    # 20MB with no newline at all
    open(p, "w").write('{"a":"' + "x" * 20_000_000 + '"}')
    cases.append((p, "one 20MB line, no newlines"))

    p = os.path.join(d, "broken.log.gz")
    open(p, "wb").write(b"not gzip at all" * 200)
    cases.append((p, "broken .gz"))

    p = os.path.join(d, "bin.log")
    open(p, "wb").write(bytes(range(256)) * 4000)
    cases.append((p, "binary content"))

    p = os.path.join(d, "utf16.log")
    open(p, "wb").write("2026-08-04 12:00:00 ERROR unicode line\n".encode("utf-16") * 300)
    cases.append((p, "utf-16 encoded"))

    p = os.path.join(d, "crlf.log")
    open(p, "w", newline="").write("2026-08-04 12:00:00 ERROR windows line\r\n" * 300)
    cases.append((p, "CRLF line endings"))

    p = os.path.join(d, "nots.log")                     # no timestamps anywhere
    open(p, "w").write("".join(f"widget {i} did a thing\n" for i in range(2000)))
    cases.append((p, "no timestamps"))

    p = os.path.join(d, "unique.log")                   # no repetition: template explosion
    open(p, "w").write("".join(f"2026-08-04 12:00:00 ERROR unique event {i} {'w'*(i % 40)}\n"
                               for i in range(60000)))
    cases.append((p, "60k distinct lines"))

    cases.append((d, "a directory"))
    cases.append((os.path.join(d, "nope.log"), "missing file"))
    return cases


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        cases = build_cases(d)
        extra = [["--dry-run"], ["--health"], ["--last", "30m", "--dry-run"]]
        for path, label in cases:
            for flags in extra:
                p = subprocess.run([sys.executable, "-m", "logsleuth", path] + flags,
                                   capture_output=True, text=True, timeout=600, cwd=ROOT)
                out = (p.stderr or "") + (p.stdout or "")
                bad = "Traceback" in out
                if bad:
                    failures += 1
                mark = "TRACEBACK" if bad else "ok"
                print(f"{label:<28}{' '.join(flags):<26}{mark}")
    print(f"\n{'FAILED' if failures else 'PASS'} — {failures} traceback(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
