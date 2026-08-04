"""Log format handling: structured logs, timestamps, multi-line events.

Real-world logs are not one format. This module sniffs what it is dealing with
once, then normalizes every line into a common shape the scanner can aggregate:
(timestamp, level, message, fields). Java/Python stack traces are folded into
the event they belong to instead of polluting the template counts.
"""
import json
import re

# --- timestamps -------------------------------------------------------------
TS_PATTERNS = [
    re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"),            # ISO / RFC3339
    re.compile(r"^\[?(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})"),          # Apache CLF
    re.compile(r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"),           # syslog
    re.compile(r"^\[?(\d{10})(?:\.\d+)?\]?[\s|]"),                            # unix epoch
    re.compile(r"^\[(\d{2}:\d{2}:\d{2})"),                                     # bare clock
]
LEVEL_PAT = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|FATAL|CRIT(?:ICAL)?|PANIC)\b")

# A continuation line belongs to the previous event: indented, or a stack frame.
CONT_PAT = re.compile(r"^(\s+|\tat\s|at\s+[\w.$]+\(|Caused by:|\.\.\.\s\d+\smore|"
                      r"File \"|\s*\w+Error:|\s*\w+Exception:|#\d+\s+0x)")

LEVEL_KEYS = ("level", "severity", "lvl", "log.level", "loglevel", "@level")
MSG_KEYS = ("msg", "message", "log", "event", "@message", "text")
TS_KEYS = ("ts", "time", "timestamp", "@timestamp", "eventTime", "date")


def timestamp_of(line):
    for pat in TS_PATTERNS:
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


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
        if s.count("=") >= 2 and " " in s:
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
