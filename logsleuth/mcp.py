"""MCP server — lets an AI agent read a log file that does not fit in its context.

An agent hitting a 2GB log has no good move. It reads the first few hundred lines,
or greps blindly, and then reasons about whatever it happened to see. That is not a
model-quality problem and a bigger model will not fix it; the file is simply larger
than any context window.

This exposes the deterministic half of logsleuth as MCP tools. The agent hands over a
path; it gets back an evidence pack — deduplicated patterns with first-seen position,
near-unique lines ranked as candidate state changes, numeric trends, error
concentration by dimension, and context windows around incident onset. Two gigabytes
become roughly 25KB, and the reduction keeps the parts that carry the answer rather
than the parts that happen to come first.

Deliberately, no model runs here. The agent *is* the model, and usually a far more
capable one than the local qwen3 the CLI uses. Our job is to make the file legible;
the reasoning is the caller's.

    logsleuth-mcp            # speaks JSON-RPC 2.0 over stdio

stdout carries the protocol and nothing else. Anything we want to say goes to stderr.
"""
import json
import os
import sys
import tempfile
import traceback

from . import __version__
from .redact import format_health, health
from .scan import UnreadableLog, build_pack, probe, scan
from .window import parse_duration, slice_file

PROTOCOL_VERSION = "2025-06-18"
MAX_PACK_CHARS = 60_000       # generous: an agent's context is larger than qwen3's

TOOLS = [
    {
        "name": "read_log_evidence",
        "description": (
            "Read an entire log file — gigabytes are fine — and return a compact "
            "evidence pack summarising what actually happened in it. Use this instead "
            "of reading, grepping or tailing a log that is too large to fit in "
            "context, and instead of guessing which part of it to sample.\n\n"
            "The pack contains: deduplicated line patterns with how often each occurs "
            "and where it first appears; near-unique lines ranked as candidate state "
            "changes (deploys, config changes, cron jobs, leader elections); numeric "
            "trends across the file (latency, memory, queue depth); how errors "
            "distribute across dimensions such as service, pod or host; and raw "
            "context windows around the point where new errors begin.\n\n"
            "Everything is computed deterministically — no model is involved and "
            "nothing leaves the machine. Note that a component logging many errors is "
            "commonly a victim of a failure rather than its cause; prefer rare events "
            "that shortly precede the first new error."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to a log file. Plain text, JSON lines, logfmt and gzip are all read; Kubernetes CRI and Docker envelopes are unwrapped."},
                "last": {"type": "string", "description": "Optional: analyse only the final window, e.g. '30m', '2h', '7d'. Seeks by byte offset, so this is fast even on a huge file."},
                "since": {"type": "string", "description": "Optional: analyse from this time onwards. Accepts '2026-08-04T02:00', '2026-08-04 02:00:00' or a bare '02:00', which is resolved against the date the log covers."},
                "until": {"type": "string", "description": "Optional: analyse up to this time."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "inspect_log_file",
        "description": (
            "Cheap sanity check on a file before committing to reading it: size, "
            "whether it is text or binary, whether it is compressed, and whether it "
            "looks like a log at all. Use this first when you are unsure what a file "
            "is, so you do not spend a turn on a core dump or a directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute path to inspect."}},
            "required": ["path"],
        },
    },
    {
        "name": "log_parse_diagnostics",
        "description": (
            "Report how well logsleuth understands a file's format — line shapes, "
            "which timestamp formats parsed, how many lines carry a level, how well "
            "lines collapse into templates. Contains NO log content, so it is safe to "
            "quote to a user or paste into a bug report. Use it when the evidence "
            "pack looks thin and you want to know whether the file was understood."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute path to diagnose."}},
            "required": ["path"],
        },
    },
]


# ---------------- evidence rendering ----------------

def render_pack(s):
    """The evidence pack as text. Same content the CLI sends its local model."""
    out = [
        f"# Log evidence: {s['total_lines']:,} lines scanned, "
        f"{s['signal_lines']:,} error-like ({s['fmt']} format)",
        "",
        "## Rare / notable events (near-unique lines, ranked as candidate state changes)",
        "\n".join(s["changes"]) or "(none found)",
        "",
        "## Signal patterns (deduplicated, with first-seen position in the file)",
        "\n".join(s["patterns"]) or "(none found)",
        "",
        "## Numeric trends (head-quartile average -> tail-quartile average)",
        "\n".join(s["trends"]) or "(no significant trends)",
        "",
        "## Error concentration by dimension",
        "\n".join(s["dim_notes"]) or "(no concentration detected)",
        "",
        "## Context window: incident onset",
        s["windows"][0] if s["windows"] else "(none)",
    ]
    if len(s["windows"]) > 1:
        out += ["", "## Context window: end of file", s["windows"][1]]
    if not s["signal_lines"]:
        out += ["", "NOTE: no error-like lines at all. This may be a degradation without "
                    "errors — rely on the numeric trends and rare events, or say the "
                    "evidence is insufficient."]
    return "\n".join(out)[:MAX_PACK_CHARS]


def windowed(path, last=None, since=None, until=None):
    """Apply a time window if asked. Returns (path, tempfile_to_remove, note)."""
    if not (last or since or until):
        return path, None, ""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    tmp.close()
    info = slice_file(path, tmp.name, since=since, until=until,
                      last=parse_duration(last) if last else None)
    if not info["ok"]:
        os.unlink(tmp.name)
        raise ValueError(f"{info['reason']} — the file has no timestamps logsleuth can "
                         f"read, so drop the time window and analyse the whole file")
    if not info["lines"]:
        os.unlink(tmp.name)
        raise ValueError("the requested window contains no lines")
    saved = 100 * (1 - info["bytes_read"] / max(info["bytes_total"], 1))
    note = f"Window: {info['lines']:,} lines"
    if saved > 5:
        note += f" (skipped {saved:.0f}% of the file by seeking)"
    if not info["sorted"]:
        note += " — file is not in chronological order, so it was filtered rather than seeked"
    return tmp.name, tmp.name, note + "\n\n"


# ---------------- tool implementations ----------------

def tool_read_log_evidence(args):
    path = args["path"]
    target, tmp, note = windowed(path, args.get("last"), args.get("since"), args.get("until"))
    try:
        pack = build_pack(scan(target))
    finally:
        if tmp:
            os.unlink(tmp)
    if not pack["total_lines"]:
        return "The file is empty."
    return note + render_pack(pack)


def tool_inspect_log_file(args):
    path = args["path"]
    # probe() raises UnreadableLog with a human sentence when the file is a directory,
    # a binary, or a broken archive; call_tool turns that into a tool error the agent
    # can act on. Reaching here means it is readable text.
    encoding = probe(path)
    size = os.path.getsize(path)
    lines = "unknown (compressed)" if path.endswith(".gz") else None
    if lines is None:
        with open(path, "rb") as fh:
            head = fh.read(1 << 20)
        nl = head.count(b"\n")
        lines = f"~{int(nl * size / max(len(head), 1)):,}" if nl else "no newlines found"
    return (f"Readable as a log.\n"
            f"size: {size:,} bytes ({size / 1e6:.1f} MB)\n"
            f"encoding: {encoding}\n"
            f"compressed: {'yes (gzip)' if path.endswith('.gz') else 'no'}\n"
            f"estimated lines: {lines}\n\n"
            f"Call read_log_evidence on it — size is not a reason to hesitate; the "
            f"scan is streaming and its memory does not grow with the file.")


def tool_log_parse_diagnostics(args):
    path = args["path"]
    h = health(path)
    sc = scan(path)
    pack = build_pack(sc)
    return format_health(h, {"templates": len(sc["templates"]),
                             "compression": sc["total"] / max(len(sc["templates"]), 1),
                             "signal": sc["signal"], "rare": len(pack["changes"]),
                             "trends": len(pack["trends"])})


HANDLERS = {
    "read_log_evidence": tool_read_log_evidence,
    "inspect_log_file": tool_inspect_log_file,
    "log_parse_diagnostics": tool_log_parse_diagnostics,
}


# ---------------- JSON-RPC plumbing ----------------

def result(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def call_tool(name, args):
    """Run a tool. Failures come back as tool errors, not protocol errors: the agent
    can act on 'that file is a directory' but not on a dead connection."""
    fn = HANDLERS.get(name)
    if fn is None:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    path = (args or {}).get("path")
    if path and not os.path.exists(path):
        return {"content": [{"type": "text", "text": f"No such file: {path}"}], "isError": True}
    try:
        return {"content": [{"type": "text", "text": fn(args or {})}]}
    except UnreadableLog as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


def handle(req):
    """Return a response dict, or None for notifications, which take no reply."""
    method, rid = req.get("method"), req.get("id")

    if method == "initialize":
        asked = (req.get("params") or {}).get("protocolVersion")
        return result(rid, {
            # Echo the client's version when it names one: it knows what it can speak,
            # and refusing a version we would have handled anyway helps nobody.
            "protocolVersion": asked or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "logsleuth", "version": __version__},
            "instructions": (
                "Use read_log_evidence for any log file too large to read directly. "
                "It reads the whole file and returns a compact summary of what happened, "
                "deterministically and without sending anything anywhere."
            ),
        })

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return result(rid, {})

    if method == "tools/list":
        return result(rid, {"tools": TOOLS})

    if method == "tools/call":
        p = req.get("params") or {}
        return result(rid, call_tool(p.get("name"), p.get("arguments")))

    if rid is None:
        return None
    return error(rid, -32601, f"Method not found: {method}")


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            stdout.write(json.dumps(error(None, -32700, "Parse error")) + "\n")
            stdout.flush()
            continue
        try:
            resp = handle(req)
        except Exception as e:                      # never let one bad call end the session
            traceback.print_exc(file=sys.stderr)
            resp = error(req.get("id"), -32603, f"Internal error: {e}")
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()


def main():
    try:
        serve()
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
