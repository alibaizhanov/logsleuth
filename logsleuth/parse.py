"""Log format handling: structured logs, timestamps, multi-line events.

Real-world logs are not one format. This module sniffs what it is dealing with
once, then normalizes every line into a common shape the scanner can aggregate:
(timestamp, level, message, fields). Java/Python stack traces are folded into
the event they belong to instead of polluting the template counts.
"""
import json
import re

# Container runtimes prefix every line: CRI (k8s) as "<ts> stdout F msg",
# Docker as a JSON envelope with a "log" field. Strip the envelope so the real
# application line underneath is what gets parsed and grouped.
CRI_PAT = re.compile(r"^(\S+)\s+(stdout|stderr)\s+([FP])\s?(.*)$")


def strip_container_envelope(line):
    """Return (inner_line, meta) after removing a CRI/Docker log wrapper."""
    m = CRI_PAT.match(line)
    if m:
        return m.group(4), {"stream": m.group(2), "ts": m.group(1)}
    if line.startswith('{"log":') or ('"stream"' in line[:60] and line.startswith("{")):
        try:
            obj = json.loads(line)
        except ValueError:
            return line, None
        if isinstance(obj, dict) and "log" in obj:
            return str(obj["log"]).rstrip("\n"), {"stream": obj.get("stream"), "ts": obj.get("time")}
    return line, None


# --- timestamps ---------------------------------------------------------------
# Real logs put the time in many shapes, and not always at the start of the line
# (OpenStack prefixes the source filename, k8s prefixes a stream marker). So we
# search a bounded prefix with one combined pattern instead of anchoring at 0.
# Every format below was taken from a real corpus, not invented.
TS_SEARCH_WINDOW = 64

TS_COMBINED = re.compile(
    r"(?P<iso>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?)"
    r"|(?P<bgl>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}(?:\.\d+)?)"
    r"|(?P<compact>\d{8}-\d{2}:\d{2}:\d{2}(?::\d{1,3})?)"
    r"|(?P<slash2>\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})"
    r"|(?P<clf>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})"
    r"|(?P<ctime>[A-Z][a-z]{2} [A-Z][a-z]{2} {1,2}\d{1,2} \d{2}:\d{2}:\d{2} \d{4})"
    r"|(?P<syslog>[A-Z][a-z]{2} {1,2}\d{1,2} \d{2}:\d{2}:\d{2})"
    r"|(?P<hdfs>\b\d{6} \d{6}\b)"
    r"|(?P<md>\b\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)"
    r"|(?P<dotmd>\b\d{2}\.\d{2} \d{2}:\d{2}:\d{2})"
    r"|(?P<epoch>\b1[0-9]{9}\b)"
)

# kind -> (strptime format, normalizer applied to the raw text first)
TS_FORMATS = {
    "iso": ("%Y-%m-%d %H:%M:%S", lambda v: v.replace("T", " ").split(".")[0].split(",")[0]),
    "bgl": ("%Y-%m-%d-%H.%M.%S", lambda v: ".".join(v.split(".")[:3])),
    "compact": ("%Y%m%d-%H:%M:%S", lambda v: ":".join(v.split(":")[:3])),
    "slash2": ("%y/%m/%d %H:%M:%S", lambda v: v),
    "clf": ("%d/%b/%Y:%H:%M:%S", lambda v: v),
    "ctime": ("%a %b %d %H:%M:%S %Y", lambda v: re.sub(r"\s+", " ", v)),
    "syslog": ("%b %d %H:%M:%S", lambda v: re.sub(r"\s+", " ", v)),
    "hdfs": ("%y%m%d %H%M%S", lambda v: v),
    "md": ("%m-%d %H:%M:%S", lambda v: v.split(".")[0]),
    "dotmd": ("%m.%d %H:%M:%S", lambda v: v),
}


def timestamp_kind(line):
    """(raw timestamp text, kind) found anywhere in the line's leading window."""
    m = TS_COMBINED.search(line[:TS_SEARCH_WINDOW])
    return (m.group(0), m.lastgroup) if m else (None, None)


def timestamp_of(line):
    return timestamp_kind(line)[0]


LEVEL_PAT = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|FATAL|CRIT(?:ICAL)?|PANIC)\b")

# A continuation line belongs to the previous event: indented, or a stack frame.
CONT_PAT = re.compile(r"^(\s+|\tat\s|at\s+[\w.$]+\(|Caused by:|\.\.\.\s\d+\smore|"
                      r"File \"|\s*\w+Error:|\s*\w+Exception:|#\d+\s+0x)")

LEVEL_KEYS = ("level", "severity", "lvl", "log.level", "loglevel", "@level")
MSG_KEYS = ("msg", "message", "log", "event", "@message", "text")
TS_KEYS = ("ts", "time", "timestamp", "@timestamp", "eventTime", "date")




def is_continuation(line):
    return bool(line) and bool(CONT_PAT.match(line)) and timestamp_of(line) is None


def sniff(sample_lines):
    """Decide the file format from a sample: json | logfmt | text."""
    js = lf = 0
    for line in sample_lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("{") and s.endswith("}"):
            try:
                if isinstance(json.loads(s), dict):
                    js += 1
                    continue
            except ValueError:
                pass
        # logfmt means the line *is* key=value pairs, not that it merely contains
        # a couple ("... logname= uid=0 euid=0" in syslog is plain text).
        toks = s.split()
        if len(toks) >= 3:
            kv = sum(1 for t in toks if re.match(r"^\w[\w.\-]*=", t))
            if kv / len(toks) > 0.6:
                lf += 1
    total = max(js + lf, 1)
    if js / total > 0.6 and js >= 3:
        return "json"
    if lf / total > 0.6 and lf >= 3:
        return "logfmt"
    return "text"


def _flatten(obj, prefix="", out=None, depth=0):
    """Flatten nested JSON into dotted scalar fields (bounded depth)."""
    if out is None:
        out = {}
    if depth > 3:
        return out
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            _flatten(v, key + ".", out, depth + 1)
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v
    return out


def parse_json_line(line):
    """Return (ts, level, message, fields) for a JSON log line, or None."""
    s = line.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    flat = _flatten(obj)
    lower = {k.lower(): k for k in flat}
    def pick(keys):
        for k in keys:
            if k in lower:
                return flat[lower[k]], lower[k]
        return None, None
    ts, ts_key = pick(TS_KEYS)
    level, lvl_key = pick(LEVEL_KEYS)
    msg, msg_key = pick(MSG_KEYS)
    fields = {k: v for k, v in flat.items() if k not in (ts_key, lvl_key, msg_key)}
    if ts is None:
        ts = timestamp_of(line)
    return (str(ts) if ts is not None else None,
            str(level).upper() if level is not None else None,
            str(msg) if msg is not None else s,
            fields)


LOGFMT_PAT = re.compile(r'(\w[\w.\-]*)=("([^"]*)"|\S+)')


def parse_logfmt_line(line):
    fields = {}
    for k, raw, quoted in LOGFMT_PAT.findall(line):
        fields[k] = quoted if raw.startswith('"') else raw
    if not fields:
        return None
    lower = {k.lower(): k for k in fields}
    def pick(keys):
        for k in keys:
            if k in lower:
                return fields[lower[k]], lower[k]
        return None, None
    ts, ts_key = pick(TS_KEYS)
    level, lvl_key = pick(LEVEL_KEYS)
    msg, msg_key = pick(MSG_KEYS)
    rest = {k: v for k, v in fields.items() if k not in (ts_key, lvl_key, msg_key)}
    if ts is None:
        ts = timestamp_of(line)
    return (ts, str(level).upper() if level else None, msg or line.strip(), rest)


def parse_text_line(line):
    ts = timestamp_of(line)
    m = LEVEL_PAT.search(line[:120])
    return ts, (m.group(1).upper() if m else None), line.strip(), {}


PARSERS = {"json": parse_json_line, "logfmt": parse_logfmt_line, "text": parse_text_line}


def parse_line(line, fmt):
    """Normalize any line to (ts, level, message, fields); falls back to text."""
    fn = PARSERS.get(fmt, parse_text_line)
    got = fn(line)
    if got is None:
        got = parse_text_line(line)
    return got
