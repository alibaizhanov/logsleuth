"""Time-window selection over a log file, without reading the whole file.

Logs are almost always written in chronological order, so the start of a window
can be found by binary search on byte offsets: seek to the middle, read a line,
compare its timestamp, halve. Twenty seeks locate the window in a file of any
size — "analyze the last 30 minutes" of a 10GB log never touches the other 9.9GB.

If the file turns out not to be sorted, we say so and fall back to a full scan.
"""
import datetime as dt
import os
import re

from .parse import TS_FORMATS, strip_container_envelope, timestamp_kind, timestamp_of

DUR = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdw])$", re.I)
UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

_FORMATS = [
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%Y-%m-%d", "%d/%b/%Y:%H:%M:%S", "%b %d %H:%M:%S", "%H:%M:%S", "%H:%M",
]


def parse_duration(text):
    m = DUR.match(text.strip())
    if not m:
        raise ValueError(f"bad duration {text!r} — use forms like 30m, 2h, 7d")
    return float(m.group(1)) * UNIT[m.group(2).lower()]


def parse_when(text, reference=None):
    """Parse an absolute time; bare clock times attach to the reference date."""
    text = text.strip().strip("[]")
    for fmt in _FORMATS:
        try:
            got = dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt and reference is not None:
            got = got.replace(year=reference.year,
                              month=got.month if "%b" in fmt or "%m" in fmt else reference.month,
                              day=got.day if "%d" in fmt else reference.day)
        return got
    raise ValueError(f"cannot parse time {text!r}")


def line_time(line, reference=None):
    """Parse this line's timestamp into a datetime, whatever shape it is written in."""
    inner, env = strip_container_envelope(line)
    envelope_ts = (env or {}).get("ts")
    if envelope_ts:
        try:
            return parse_when(str(envelope_ts).split("+")[0].split("Z")[0].split(".")[0], reference)
        except ValueError:
            pass
    raw, kind = timestamp_kind(inner)
    if not raw:
        raw, kind = timestamp_kind(line)
    if not raw:
        return None
    if kind == "epoch":
        try:
            return dt.datetime.fromtimestamp(int(raw), dt.timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            return None
    fmt, prep = TS_FORMATS.get(kind, (None, None))
    if not fmt:
        return None
    try:
        got = dt.datetime.strptime(prep(raw), fmt)
    except ValueError:
        return None
    # formats without a year (syslog, Android, Proxifier) borrow it from the file
    if "%Y" not in fmt and "%y" not in fmt:
        base = reference or dt.datetime.now()
        got = got.replace(year=base.year)
    return got


def _read_line_at(fh, offset):
    """Read the first complete line at or after a byte offset."""
    fh.seek(offset)
    if offset:
        fh.readline()
    pos = fh.tell()
    return fh.readline(), pos


def first_last_time(path):
    """Timestamps of the first and last dated lines, plus a sortedness check."""
    size = os.path.getsize(path)
    with open(path, errors="replace") as fh:
        first = None
        for _ in range(200):
            line = fh.readline()
            if not line:
                break
            first = line_time(line)
            if first:
                break
        fh.seek(max(0, size - 65536))
        fh.readline()
        last = None
        for line in fh:
            t = line_time(line, reference=first)
            if t:
                last = t
    return first, last


def find_offset(path, target, reference=None):
    """Binary-search the byte offset of the first line at or after `target`."""
    size = os.path.getsize(path)
    lo, hi, best = 0, size, size
    with open(path, errors="replace") as fh:
        for _ in range(60):
            if lo >= hi:
                break
            mid = (lo + hi) // 2
            line, pos = _read_line_at(fh, mid)
            if not line:
                hi = mid
                continue
            t = line_time(line, reference)
            if t is None:                       # undated line: nudge forward
                lo = pos + len(line)
                continue
            if t >= target:
                best = min(best, pos)
                hi = mid
            else:
                lo = pos + len(line)
    return best


def looks_sorted(path, probes=8):
    """Cheap monotonicity check at evenly spaced offsets."""
    size = os.path.getsize(path)
    times = []
    with open(path, errors="replace") as fh:
        ref = None
        for i in range(probes):
            line, _ = _read_line_at(fh, size * i // probes)
            if not line:
                continue
            t = line_time(line, ref)
            if t:
                ref = ref or t
                times.append(t)
    return all(a <= b for a, b in zip(times, times[1:])) if len(times) > 2 else True


def slice_file(path, out_path, since=None, until=None, last=None):
    """Write the requested time window to out_path. Returns a description dict.

    `since` and `until` may be datetimes or strings. Strings are parsed here rather
    than by the caller, because only here do we know the file's own date — so a bare
    "02:00" means two in the morning on the day the log covers, not on 1 January 1900,
    which is what a caller parsing it blind would produce.
    """
    first, latest = first_last_time(path)
    if not first or not latest:
        return {"ok": False, "reason": "no parseable timestamps in this file"}
    if isinstance(since, str):
        since = parse_when(since, reference=first)
    if isinstance(until, str):
        until = parse_when(until, reference=first)
    if last is not None:
        since = latest - dt.timedelta(seconds=last)
    sorted_ok = looks_sorted(path)
    size = os.path.getsize(path)

    start = find_offset(path, since, first) if (since and sorted_ok) else 0
    written = kept = 0
    with open(path, errors="replace") as fh, open(out_path, "w") as out:
        fh.seek(start)
        if start:
            fh.readline()
        for line in fh:
            t = line_time(line, first)
            if t:
                if since and t < since:
                    if sorted_ok:
                        continue
                    continue
                if until and t > until:
                    if sorted_ok:
                        break
                    continue
            out.write(line)
            kept += 1
            written += len(line)
    return {"ok": True, "sorted": sorted_ok, "first": first, "last": latest,
            "since": since, "until": until, "lines": kept,
            "bytes_read": size - start if sorted_ok else size, "bytes_total": size}
