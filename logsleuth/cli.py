#!/usr/bin/env python3
"""logsleuth — local AI root-cause analysis for production logs.

Nothing leaves your machine: deterministic preprocessing + a local LLM via Ollama.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

TS_PAT = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")

from . import __version__, backend, render
from .redact import format_health, health
from .scan import UnreadableLog, build_pack, scan, spool_stdin
from .window import parse_duration, parse_when, slice_file

OLLAMA_URL = os.environ.get("LOGSLEUTH_OLLAMA_URL", "http://localhost:11434")
# No hardcoded default: the model is chosen to fit the machine's memory unless
# the user names one. A model that swaps is worse than a smaller model that fits.
DEFAULT_MODEL = os.environ.get("LOGSLEUTH_MODEL") or None
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

OUTPUT FORMAT — use these exact headings, in this order, nothing before or after.
An engineer is reading this at 3am: lead with the answer, keep every section tight.

## Root cause
One or two sentences naming the failing component or change, then "Confidence: high|medium|low".
Then 2-4 bullets, each quoting a real evidence line.
## Ruled out
1-3 bullets: loud signals you deliberately did NOT blame, and why. Omit the section if none.
## Timeline
3-6 bullets, ordered, with timestamps where present.
## Next steps
2-4 concrete actions, most urgent first.

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

def confirm(question: str, assume_yes: bool = False) -> bool:
    """Ask on the terminal. Reads /dev/tty so a piped log on stdin still works."""
    if assume_yes:
        return True
    try:
        tty = open("/dev/tty", "r+")
    except OSError:
        if not sys.stdin.isatty():     # a piped log, or a script: nobody to ask
            return False
        sys.stderr.write(f"\n{question} [Y/n] ")
        sys.stderr.flush()
        return sys.stdin.readline().strip().lower() in ("", "y", "yes")
    with tty:
        tty.write(f"\n{question} [Y/n] ")
        tty.flush()
        answer = tty.readline().strip().lower()
    return answer in ("", "y", "yes")


def ensure_backend(model, assume_yes: bool = False) -> str:
    """Get to a state where a local model can answer. Returns the model to use."""
    def say(msg, cr=False):
        sys.stderr.write(("\r" if cr else "") + f"{msg}" + ("" if cr else "\n"))
        sys.stderr.flush()

    resolved, ready = backend.ensure(
        model, say=say, ask=lambda q: confirm(q, assume_yes), url=OLLAMA_URL)
    if not ready:
        die("no local model available.",
            "logsleuth runs the model on your machine so your logs never leave it.\n"
            "  set it up automatically:  logsleuth demo --yes\n"
            f"  or do it by hand:        install https://ollama.com/download, "
            f"then `ollama pull {resolved}`")
    return resolved


ROOT_CAUSE_RE = re.compile(r"^#{1,4}\s*root cause", re.I | re.M)

FORMAT_REMINDER = (
    "\n\nYour previous answer did not follow the required format. Reply again using "
    "exactly these headings and nothing else: '## Root cause', '## Ruled out', "
    "'## Timeline', '## Next steps'. Start with '## Root cause'."
)


def analyze(prompt: str, model: str) -> str:
    return "".join(analyze_stream(prompt, model))


def has_root_cause(report: str) -> bool:
    return bool(ROOT_CAUSE_RE.search(report or ""))


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

def resolve_input(paths):
    """Return a path to scan. stdin is spooled; several files are merged to a temp file."""
    if len(paths) == 1:
        p = paths[0]
        if p == "demo":
            status("demo mode: a bundled realistic incident "
                   "(a deploy shrinks a Postgres pool -> timeouts -> retry storm -> OOM)")
            return os.path.join(os.path.dirname(__file__), "data", "demo_incident.log"), None
        if p == "-":
            return spool_stdin(sys.stdin), None
        if not os.path.exists(p):
            die(f"no such file: {p}")
        return p, None

    # Multiple files: tag each line with its source and merge chronologically, so
    # the source file becomes an analysis dimension (src=…) the model can use.
    entries, seq, ts_hits, total = [], 0, 0, 0
    for p in paths:
        try:
            fh = open(p, errors="replace")
        except OSError as e:
            die(str(e))
        src, last_ts = os.path.basename(p), ""
        with fh:
            for line in fh:
                line = line.rstrip("\n")
                m = TS_PAT.match(line)
                if m:
                    last_ts = m.group(1)
                    ts_hits += 1
                total += 1
                entries.append((last_ts, seq, f"{line} src={src}"))
                seq += 1
    if total and ts_hits / total > 0.5:
        entries.sort(key=lambda e: (e[0], e[1]))
        status(f"merged {len(paths)} files ({total:,} lines) chronologically; source is a dimension (src=…)")
    else:
        status(f"concatenated {len(paths)} files ({total:,} lines); source is a dimension (src=…)")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    tmp.write("\n".join(e[2] for e in entries))
    tmp.close()
    return tmp.name, tmp.name


# ---------------- CLI ----------------

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="logsleuth",
        description="Local AI root-cause analysis for production logs. Nothing leaves your machine.")
    ap.add_argument("logfiles", nargs="+", metavar="logfile",
                    help="one or more log files (merged by timestamp, source becomes an analysis "
                         "dimension), '-' for stdin, or 'demo' for a bundled sample incident")
    ap.add_argument("--health", action="store_true",
                    help="print parse diagnostics only — no log content, safe to share in a bug report")
    ap.add_argument("--last", metavar="DUR",
                    help="analyze only the last window, e.g. 30m, 2h, 7d")
    ap.add_argument("--since", metavar="TIME", help="analyze from this time onwards")
    ap.add_argument("--until", metavar="TIME", help="analyze up to this time")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="local model to use (default: chosen to fit this machine's memory)")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="answer yes to first-run setup prompts (unattended install)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--plain", action="store_true", help="plain markdown output (no colors/graphs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the evidence pack that WOULD be sent to the local model, then exit")
    ap.add_argument("--version", action="version", version=f"logsleuth {__version__}")
    args = ap.parse_args()

    path, tmp = resolve_input(args.logfiles)

    if args.health:
        h = health(path)
        sc = scan(path)
        pack = build_pack(sc)
        print(format_health(h, {"templates": len(sc["templates"]),
                                "compression": sc["total"] / max(len(sc["templates"]), 1),
                                "signal": sc["signal"], "rare": len(pack["changes"]),
                                "trends": len(pack["trends"])}))
        if tmp:
            os.unlink(tmp)
        return

    if args.last or args.since or args.until:
        win = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        win.close()
        try:
            # Strings go through: slice_file resolves them against the file's own
            # date, so `--since 02:00` means this log's 02:00, not year 1900.
            info = slice_file(path, win.name, since=args.since, until=args.until,
                              last=parse_duration(args.last) if args.last else None)
        except ValueError as e:
            die(str(e))
        if not info["ok"]:
            die(info["reason"], "the file has no timestamps logsleuth can read; drop --last/--since")
        if not info["sorted"]:
            status("file is not in chronological order — filtering the whole file instead of seeking")
        saved = 100 * (1 - info["bytes_read"] / max(info["bytes_total"], 1))
        status(f"window: {info['lines']:,} lines"
               f"{f' (skipped {saved:.0f}% of the file by seeking)' if saved > 5 else ''}")
        if not info["lines"]:
            die("the requested window contains no lines")
        if tmp:
            os.unlink(tmp)
        path, tmp = win.name, win.name

    t_scan = time.monotonic()
    s = build_pack(scan(path))
    if tmp:
        os.unlink(tmp)
    if not s["total_lines"]:
        die("input is empty")
    cores = f" on {s['workers']} cores" if s.get("workers", 1) > 1 else ""
    status(f"scanned {s['total_lines']:,} lines in {time.monotonic() - t_scan:.1f}s{cores} | "
           f"{s['signal_lines']:,} signal | {len(s['changes'])} rare events | {len(s['trends'])} trends")
    prompt = build_prompt(s)

    if args.dry_run:
        print(prompt)
        return

    args.model = ensure_backend(args.model, args.yes)
    t0 = time.monotonic()
    pretty = render.supports_pretty(force_plain=args.plain) and not args.json

    if pretty:
        # everything deterministic shows up instantly; the model report streams in below it
        print(render.render_header(s, args.model))
        sys.stdout.flush()
        buf = collected = ""
        try:
            for piece in analyze_stream(prompt, args.model):
                buf += piece
                collected += piece
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
        if not has_root_cause(collected + buf):
            status("model drifted from the report format — asking once more")
            try:
                for line in analyze(prompt + FORMAT_REMINDER, args.model).splitlines():
                    out = render.colorize_md_line(line)
                    if out:
                        print(out)
            except urllib.error.URLError as e:
                die(f"ollama request failed: {e}")
        print(f"\n {render.GREY}─ done in {time.monotonic() - t0:.0f}s · "
              f"local model, zero bytes sent anywhere{render.RESET}\n")
        return

    status(f"analyzing with local model {args.model} (first run may take ~1-2 min)…")
    try:
        report = analyze(prompt, args.model)
        if not has_root_cause(report):
            status("model drifted from the report format — asking once more")
            report = analyze(prompt + FORMAT_REMINDER, args.model)
    except urllib.error.URLError as e:
        die(f"ollama request failed: {e}")

    if args.json:
        print(json.dumps({"model": args.model, "stats": {k: s[k] for k in ("total_lines", "signal_lines")},
                          "report_markdown": report}, ensure_ascii=False, indent=2))
    else:
        print(report)


def cli():
    """Entry point with a safety net: an unexpected failure must never look like a crash."""
    try:
        main()
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        sys.exit(130)
    except UnreadableLog as e:
        die(str(e))
    except BrokenPipeError:
        sys.exit(0)
    except Exception as e:                                   # noqa: BLE001 - deliberate catch-all
        sys.stderr.write(color(
            f"\nlogsleuth failed on this input: {type(e).__name__}: {e}\n"
            "Nothing was sent anywhere — the failure is local.\n\n"
            "To help fix it, run:\n"
            "    logsleuth --health <your file>\n"
            "It prints parse diagnostics only (counts, formats, line shapes) with no log\n"
            "content, and can be attached to an issue at\n"
            "https://github.com/alibaizhanov/logsleuth/issues\n", C_RED))
        sys.exit(1)


if __name__ == "__main__":
    cli()
