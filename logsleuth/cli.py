#!/usr/bin/env python3
"""logsleuth — local AI root-cause analysis for production logs.

Nothing leaves your machine: deterministic preprocessing + a local LLM via Ollama.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

from . import __version__, render

OLLAMA_URL = os.environ.get("LOGSLEUTH_OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LOGSLEUTH_MODEL", "qwen3:8b")
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
DIM_PAT = re.compile(r"\b(node|pod|host|instance|shard|zone|region|container|build|member|id|src)=([\w.-]+)")

C_RESET, C_BOLD, C_DIM, C_CYAN, C_YELL, C_RED = "\033[0m", "\033[1m", "\033[2m", "\033[36m", "\033[33m", "\033[31m"


def color(s: str, c: str) -> str:
    return f"{c}{s}{C_RESET}" if sys.stderr.isatty() else s


def status(msg: str) -> None:
    sys.stderr.write(color(f"[logsleuth] {msg}\n", C_DIM))


def die(msg: str, hint: str = "") -> None:
    sys.stderr.write(color(f"error: {msg}\n", C_RED))
    if hint:
        sys.stderr.write(f"{hint}\n")
    sys.exit(1)


# ---------------- preprocessing (deterministic, local) ----------------

def normalize(line: str) -> str:
    """Collapse a log line to its template so identical events group together.

    Order matters: strip timestamps FIRST, otherwise digit substitution mangles
    them and every second becomes its own 'unique' template.
    """
    line = TS_PAT.sub("<ts>", line)
    line = re.sub(r"\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?Z?", "<t>", line)   # any remaining clock
    line = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", line, flags=re.I)
    line = re.sub(r"\b\d+\.\d+\.\d+\.\d+\b", "<ip>", line)
    line = re.sub(r"<\d+>", "<id>", line)
    line = re.sub(r"0x[0-9a-f]+", "<hex>", line, flags=re.I)
    line = re.sub(r"\d+", "<n>", line)                                 # every number, boundaries unreliable next to Z/ms
    return line.strip()


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

    # --- Rare-event detection (vocabulary-free) ---------------------------------
    # Normal operation repeats: "handled request" appears thousands of times.
    # A state change — a deploy, an eviction, a migration, a leader switch — is
    # structurally near-unique. So we rank by RARITY, not by keywords, which
    # generalizes across stacks, vendors and phrasings. Known change words only
    # act as a score boost, never as a gate.
    all_tpl = {}
    for i, l in enumerate(lines):
        if not l.strip():
            continue
        st = all_tpl.setdefault(normalize(l), {"count": 0, "first": i, "line": l.strip()})
        st["count"] += 1

    onset_idx = None
    for i in sig_idx:
        if pat_stats.get(normalize(lines[i]), {}).get("first", 0) / total > 0.03:
            onset_idx = i
            break
    if onset_idx is None and sig_idx:
        onset_idx = sig_idx[0]

    rare_max = max(3, int(total * 0.002))
    scored = []
    for tpl, st in all_tpl.items():
        if st["count"] > rare_max:
            continue
        i = st["first"]
        score = 3.0 / (st["count"] + 1)                      # rarer = more suspicious
        if onset_idx is not None:
            gap = (onset_idx - i) / total
            if 0 <= gap < 0.35:
                score += 3.0 * (1 - gap / 0.35)              # shortly BEFORE the incident
            elif gap < 0:
                score += 0.4                                  # during/after: still notable
        if CHANGE_PAT.search(st["line"]):
            score += 1.5                                      # known change vocabulary: a hint
        if SIGNAL_PAT.search(st["line"]):
            score -= 0.8                                      # errors already have their own section
        scored.append((score, i, st["count"], st["line"]))
    scored.sort(key=lambda x: -x[0])

    changes, change_pcts = [], []
    for _, i, cnt, line in scored[:18]:
        seen = f" (x{cnt} in file)" if cnt > 1 else ""
        rel = ""
        if onset_idx is not None:
            rel = " BEFORE first incident signal" if i < onset_idx else " after incident started"
        changes.append(f"(line {i+1}, {round(100*i/total)}% of file{seen}{rel}) {line[:220]}")
        change_pcts.append(100 * i / total)

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
                           f"(x{ratio:.1f}, {len(pts)} samples across file)",
                           (f"{key} {head:.0f}→{tail:.0f}{unit}",
                            [v for _, v in pts], "up" if ratio > 1 else "down")))
    trends.sort(key=lambda x: -x[0])
    trend_series = [t[2] for t in trends[:12]]
    trends = [t[1] for t in trends[:12]]

    sig_set = set(sig_idx)
    dims_err, dims_all = defaultdict(Counter), defaultdict(set)
    for i, l in enumerate(lines):
        for dim, val in DIM_PAT.findall(l):
            dims_all[dim].add(val)
            if i in sig_set:
                dims_err[dim][val] += 1
    dim_notes = []
    for dim, cnt in dims_err.items():
        top, top_n = cnt.most_common(1)[0]
        share = top_n / sum(cnt.values())
        universe = dims_all[dim]
        if share > 0.7 and len(universe) > 1:
            healthy = sorted(universe - {top})[:4]
            others = (", ".join(v for v, _ in cnt.most_common()[1:4])
                      or f"none — {', '.join(healthy)} are error-free")
            dim_notes.append(f"{dim}: {round(share*100)}% of all error-like lines have {dim}={top} "
                             f"(other values: {others})")

    windows = []
    if sig_idx:
        onset = next((i for i in sig_idx if pat_stats[normalize(lines[i])]["first"] / total > 0.03), sig_idx[0])
        windows.append("\n".join(lines[max(0, onset - 15):onset + 15]))
        last = sig_idx[-1]
        if last - onset > 40:
            windows.append("\n".join(lines[max(0, last - 15):last + 15]))

    return {"total_lines": total, "signal_lines": len(sig_idx), "patterns": patterns,
            "changes": changes, "trends": trends, "dim_notes": dim_notes, "windows": windows,
            "sig_positions": sig_idx, "change_pcts": change_pcts, "trend_series": trend_series}


PROMPT = """You are an experienced SRE doing incident root-cause analysis from preprocessed log evidence.

HARD RULES:
- Cite only lines that actually appear in the evidence below. NEVER invent log content, \
timestamps, or component names not present here.
- If the evidence is insufficient for a confident diagnosis, say exactly that and list \
what additional data you would need. An honest "insufficient evidence" beats a fabricated story.
- Frequency is not importance: patterns marked "PRESENT FROM FILE START" existed before the \
incident and are usually baseline noise — do not name them as root cause unless independent \
evidence supports it. Prefer quiet-but-new signals and monotonic trends over loud old ones.
- Check whether any RARE event precedes the first incident signal — recent changes are prime suspects.
- Symptoms are not causes: if threads/queues/memory are exhausted, ask WHAT exhausted them \
and walk the causal chain as far back as the evidence allows.

Produce a concise incident report in markdown:
## Symptom (2-3 sentences)
## Timeline (ordered, with timestamps where present)
## Root cause hypothesis — name the failing component/change; confidence high/medium/low; \
evidence lines quoted verbatim
## Ruled out — loud signals you deliberately did NOT blame, and why
## Suggested next steps (3-5 concrete actions)

=== RARE / NOTABLE EVENTS (near-unique lines — candidate state changes, ranked by suspicion) ===
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
            "logsleuth uses a local model via Ollama so your logs never leave this machine.\n"
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
    return "".join(analyze_stream(prompt, model))


def analyze_stream(prompt: str, model: str):
    """Yield report text chunks as the local model generates them."""
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps({"model": model,
                         "messages": [{"role": "user", "content": prompt}],
                         "stream": True,
                         "options": {"temperature": 0.2, "num_ctx": 10240}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            if not raw.strip():
                continue
            chunk = json.loads(raw)
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                yield piece
            if chunk.get("done"):
                break


# ---------------- input handling ----------------

def read_inputs(paths):
    if len(paths) == 1:
        p = paths[0]
        if p == "demo":
            demo = os.path.join(os.path.dirname(__file__), "data", "demo_incident.log")
            status("demo mode: analyzing a bundled realistic incident "
                   "(a deploy shrinks a Postgres pool -> timeouts -> retry storm -> OOM)")
            return open(demo, errors="replace").read()
        if p == "-":
            return sys.stdin.read()
        try:
            return open(p, errors="replace").read()
        except OSError as e:
            die(str(e))

    # Multiple files: tag every line with its source and merge chronologically.
    # Lines without a timestamp (tracebacks, continuations) inherit the previous
    # line's timestamp from the same file, so stack traces stay attached.
    entries, seq, ts_hits, total = [], 0, 0, 0
    for p in paths:
        try:
            raw = open(p, errors="replace").read()
        except OSError as e:
            die(str(e))
        src = os.path.basename(p)
        last_ts = ""
        for line in raw.splitlines():
            m = TS_PAT.match(line)
            if m:
                last_ts = m.group(1)
                ts_hits += 1
            total += 1
            entries.append((last_ts, seq, f"{line} src={src}"))
            seq += 1
    if total and ts_hits / total > 0.5:
        entries.sort(key=lambda e: (e[0], e[1]))
        status(f"merged {len(paths)} files ({total:,} lines) chronologically; "
               f"source file is an analysis dimension (src=…)")
    else:
        status(f"concatenated {len(paths)} files ({total:,} lines) — too few timestamps to merge; "
               f"source file is an analysis dimension (src=…)")
    return "\n".join(e[2] for e in entries)


# ---------------- CLI ----------------

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="logsleuth",
        description="Local AI root-cause analysis for production logs. Nothing leaves your machine.")
    ap.add_argument("logfiles", nargs="+", metavar="logfile",
                    help="one or more log files (merged by timestamp, source becomes an analysis "
                         "dimension), '-' for stdin, or 'demo' for a bundled sample incident")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--plain", action="store_true", help="plain markdown output (no colors/graphs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the evidence pack that WOULD be sent to the local model, then exit")
    ap.add_argument("--version", action="version", version=f"logsleuth {__version__}")
    args = ap.parse_args()

    text = read_inputs(args.logfiles)
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
    t0 = time.monotonic()
    pretty = render.supports_pretty(force_plain=args.plain) and not args.json

    if pretty:
        # everything deterministic shows up instantly; the model report streams in below it
        print(render.render_header(s, args.model))
        sys.stdout.flush()
        buf = ""
        try:
            for piece in analyze_stream(prompt, args.model):
                buf += piece
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    out = render.colorize_md_line(line)
                    if out:
                        print(out)
                        sys.stdout.flush()
        except urllib.error.URLError as e:
            die(f"ollama request failed: {e}")
        if buf.strip():
            print(render.colorize_md_line(buf))
        print(f"\n {render.GREY}─ done in {time.monotonic() - t0:.0f}s · "
              f"local model, zero bytes sent anywhere{render.RESET}\n")
        return

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
