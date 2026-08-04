#!/usr/bin/env python3
"""loglens — local AI root-cause analysis for production logs.

Nothing leaves your machine: deterministic preprocessing + a local LLM via Ollama.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

from . import __version__

OLLAMA_URL = os.environ.get("LOGLENS_OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LOGLENS_MODEL", "qwen3:8b")
MAX_CHARS_TO_MODEL = 26000

SIGNAL_PAT = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|WARN(?:ING)?|Exception|Traceback|panic|SIGSEGV|OOM|refused|"
    r"timeout|timed out|failed|failure|rejected|exceeded|aborted|unavailable|5\d\d)\b", re.I)
CHANGE_PAT = re.compile(
    r"\b(deploy|deployment|migration|migrat|feature flag|flag .{0,20}enabled|config(?:uration)?"
    r"|rollout|rotation|version|commit|upgraded?|restarted?|applied|joined|drained"
    r"|backup|cron|job .{0,20}started|maintenance)\b", re.I)
TS_PAT = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")
NUM_PAT = re.compile(r"\b([a-zA-Z_][a-zA-Z_0-9]{2,30})=(\d+(?:\.\d+)?)(ms|MB|GB|%|s|k)?\b")
DIM_PAT = re.compile(r"\b(node|pod|host|instance|shard|zone|region|container|build|member|id)=([\w.-]+)")

C_RESET, C_BOLD, C_DIM, C_CYAN, C_YELL, C_RED = "\033[0m", "\033[1m", "\033[2m", "\033[36m", "\033[33m", "\033[31m"


def color(s: str, c: str) -> str:
    return f"{c}{s}{C_RESET}" if sys.stderr.isatty() else s


def status(msg: str) -> None:
    sys.stderr.write(color(f"[loglens] {msg}\n", C_DIM))


def die(msg: str, hint: str = "") -> None:
    sys.stderr.write(color(f"error: {msg}\n", C_RED))
    if hint:
        sys.stderr.write(f"{hint}\n")
    sys.exit(1)


# ---------------- preprocessing (deterministic, local) ----------------

def normalize(line: str) -> str:
    line = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", line, flags=re.I)
    line = re.sub(r"\b\d+\.\d+\.\d+\.\d+\b", "<ip>", line)
    line = re.sub(r"<\d+>", "<id>", line)
    line = re.sub(r"\b\d{3,}\b", "<n>", line)
    return TS_PAT.sub("<ts>", line).strip()


def preprocess(text: str) -> dict:
    lines = text.splitlines()
    total = max(len(lines), 1)
    sig_idx = [i for i, l in enumerate(lines) if SIGNAL_PAT.search(l)]

    pat_stats = {}
    for i in sig_idx:
        p = normalize(lines[i])
        st = pat_stats.setdefault(p, {"count": 0, "first": i, "last": i})
        st["count"] += 1
        st["last"] = i
    patterns = []
    for p, st in sorted(pat_stats.items(), key=lambda kv: -kv[1]["count"])[:18]:
        first_pct = round(100 * st["first"] / total)
        note = ("PRESENT FROM FILE START — likely pre-existing baseline noise"
                if first_pct <= 3 else f"first appears at {first_pct}% of file")
        patterns.append(f"{st['count']:6d}x  [{note}]  {p[:180]}")

    changes = []
    for i, l in enumerate(lines):
        if CHANGE_PAT.search(l) and not SIGNAL_PAT.search(l):
            changes.append(f"(line {i+1}, {round(100*i/total)}% of file) {l.strip()[:220]}")
        if len(changes) >= 15:
            break

    series = defaultdict(list)
    for i, l in enumerate(lines):
        for key, val, unit in NUM_PAT.findall(l):
            if key.lower() in ("rid", "id", "txid", "commit", "status", "retry"):
                continue
            series[(key, unit)].append((i, float(val)))
    trends = []
    for (key, unit), pts in series.items():
        if len(pts) < 12:
            continue
        q = max(len(pts) // 4, 1)
        head = sum(v for _, v in pts[:q]) / q
        tail = sum(v for _, v in pts[-q:]) / q
        if head == 0 and tail == 0:
            continue
        ratio = (tail + 1e-9) / (head + 1e-9)
        if ratio >= 1.5 or ratio <= 0.66:
            direction = "GREW" if ratio > 1 else "DROPPED"
            trends.append((abs(ratio if ratio > 1 else 1 / ratio),
                           f"{key}: {direction} {head:.1f}{unit} -> {tail:.1f}{unit} "
                           f"(x{ratio:.1f}, {len(pts)} samples across file)"))
    trends.sort(key=lambda x: -x[0])
    trends = [t for _, t in trends[:12]]

    dims = defaultdict(Counter)
    for i in sig_idx:
        for dim, val in DIM_PAT.findall(lines[i]):
            dims[dim][val] += 1
    dim_notes = []
    for dim, cnt in dims.items():
        top, top_n = cnt.most_common(1)[0]
        share = top_n / sum(cnt.values())
        if share > 0.7 and len(cnt) > 1:
            dim_notes.append(f"{dim}: {round(share*100)}% of all error-like lines have {dim}={top} "
                             f"(others: {', '.join(v for v, _ in cnt.most_common()[1:4])})")

    windows = []
    if sig_idx:
        onset = next((i for i in sig_idx if pat_stats[normalize(lines[i])]["first"] / total > 0.03), sig_idx[0])
        windows.append("\n".join(lines[max(0, onset - 15):onset + 15]))
        last = sig_idx[-1]
        if last - onset > 40:
            windows.append("\n".join(lines[max(0, last - 15):last + 15]))

    return {"total_lines": total, "signal_lines": len(sig_idx), "patterns": patterns,
            "changes": changes, "trends": trends, "dim_notes": dim_notes, "windows": windows}


PROMPT = """You are an experienced SRE doing incident root-cause analysis from preprocessed log evidence.

HARD RULES:
- Cite only lines that actually appear in the evidence below. NEVER invent log content, \
timestamps, or component names not present here.
- If the evidence is insufficient for a confident diagnosis, say exactly that and list \
what additional data you would need. An honest "insufficient evidence" beats a fabricated story.
- Frequency is not importance: patterns marked "PRESENT FROM FILE START" existed before the \
incident and are usually baseline noise — do not name them as root cause unless independent \
evidence supports it. Prefer quiet-but-new signals and monotonic trends over loud old ones.
- Check whether any CHANGE event (deploy/migration/flag/config/cron job) precedes the first \
incident signal — recent changes are prime suspects.
- Symptoms are not causes: if threads/queues/memory are exhausted, ask WHAT exhausted them \
and walk the causal chain as far back as the evidence allows.

Produce a concise incident report in markdown:
## Symptom (2-3 sentences)
## Timeline (ordered, with timestamps where present)
## Root cause hypothesis — name the failing component/change; confidence high/medium/low; \
evidence lines quoted verbatim
## Ruled out — loud signals you deliberately did NOT blame, and why
## Suggested next steps (3-5 concrete actions)

=== CHANGE EVENTS (deploys, migrations, flags, config, jobs) ===
{changes}

=== SIGNAL PATTERNS (deduplicated, with first-seen position) ===
{patterns}

=== NUMERIC TRENDS across the file (head-quartile avg -> tail-quartile avg) ===
{trends}

=== ERROR CONCENTRATION BY DIMENSION ===
{dims}

=== CONTEXT WINDOW: incident onset ===
{window0}

=== CONTEXT WINDOW: incident peak/end ===
{window1}

Stats: {total_lines} lines total, {signal_lines} signal lines. {empty_note}
"""


def build_prompt(s: dict) -> str:
    windows = s["windows"] + ["", ""]
    empty_note = ""
    if s["signal_lines"] == 0:
        empty_note = ("NOTE: zero error-like lines found. This may be a degradation-without-errors "
                      "incident — rely on NUMERIC TRENDS and CHANGE EVENTS, or state that evidence is insufficient.")
    return PROMPT.format(
        changes="\n".join(s["changes"]) or "(none found)",
        patterns="\n".join(s["patterns"]) or "(none found)",
        trends="\n".join(s["trends"]) or "(no significant trends)",
        dims="\n".join(s["dim_notes"]) or "(no concentration detected)",
        window0=windows[0][:7000], window1=windows[1][:5000],
        total_lines=s["total_lines"], signal_lines=s["signal_lines"], empty_note=empty_note,
    )[:MAX_CHARS_TO_MODEL]


# ---------------- Ollama plumbing ----------------

def ollama_get(path: str):
    with urllib.request.urlopen(f"{OLLAMA_URL}{path}", timeout=5) as r:
        return json.loads(r.read())


def check_ollama(model: str) -> None:
    try:
        ollama_get("/api/version")
    except (urllib.error.URLError, OSError):
        die("Ollama is not running.",
            "loglens uses a local model via Ollama so your logs never leave this machine.\n"
            "  install:  https://ollama.com/download\n"
            "  then run: ollama serve")
    try:
        tags = [m["name"] for m in ollama_get("/api/tags").get("models", [])]
    except Exception:
        tags = []
    if model not in tags and f"{model}:latest" not in tags:
        die(f"model '{model}' is not installed.",
            f"  run: ollama pull {model}\n"
            f"  (~5GB download, one time; needs ~6GB free RAM)")


def analyze(prompt: str, model: str) -> str:
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps({"model": model,
                         "messages": [{"role": "user", "content": prompt}],
                         "stream": False,
                         "options": {"temperature": 0.2, "num_ctx": 10240}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())["message"]["content"]


# ---------------- CLI ----------------

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="loglens",
        description="Local AI root-cause analysis for production logs. Nothing leaves your machine.")
    ap.add_argument("logfile", help="path to a log file, or '-' to read stdin")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the evidence pack that WOULD be sent to the local model, then exit")
    ap.add_argument("--version", action="version", version=f"loglens {__version__}")
    args = ap.parse_args()

    if args.logfile == "-":
        text = sys.stdin.read()
    else:
        try:
            text = open(args.logfile, errors="replace").read()
        except OSError as e:
            die(str(e))
    if not text.strip():
        die("input is empty")

    s = preprocess(text)
    status(f"{s['total_lines']} lines | {s['signal_lines']} signal | "
           f"{len(s['changes'])} change events | {len(s['trends'])} trends")
    prompt = build_prompt(s)

    if args.dry_run:
        print(prompt)
        return

    check_ollama(args.model)
    status(f"analyzing with local model {args.model} (first run may take ~1-2 min)…")
    try:
        report = analyze(prompt, args.model)
    except urllib.error.URLError as e:
        die(f"ollama request failed: {e}")

    if args.json:
        print(json.dumps({"model": args.model, "stats": {k: s[k] for k in ("total_lines", "signal_lines")},
                          "report_markdown": report}, ensure_ascii=False, indent=2))
    else:
        print(report)


if __name__ == "__main__":
    main()
