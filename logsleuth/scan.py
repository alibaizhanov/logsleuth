"""Streaming, parallel, bounded-memory log scanner.

A log of any size is read once, in byte-range chunks across CPU cores, and only
aggregates are kept: line templates with counts, decimated numeric series,
dimension counters, an error-density histogram. Memory stays flat regardless of
file size; context windows are fetched afterwards with a targeted seek.
"""
import os
import re
import tempfile
from collections import Counter, defaultdict, deque
from concurrent.futures import ProcessPoolExecutor

from .drain import Drain
from .parse import is_continuation, parse_line, sniff, strip_container_envelope, timestamp_of

CHANGE_PAT = re.compile(
    r"\b(deploy|deployment|migration|migrat|feature flag|flag .{0,20}enabled|config(?:uration)?"
    r"|rollout|rotation|version|commit|upgraded?|restarted?|applied|joined|drained"
    r"|backup|cron|job .{0,20}started|maintenance)\b", re.I)
NUM_PAT = re.compile(r"\b([a-zA-Z_][a-zA-Z_0-9]{2,30})=(\d+(?:\.\d+)?)(ms|MB|GB|%|s|k)?\b")
DIM_PAT = re.compile(r"\b(node|pod|host|instance|shard|zone|region|container|build|member|id|src)=([\w.-]+)")
# Lowercase once, then a case-sensitive scan: 2x faster than re.IGNORECASE.
SIGNAL_LOWER = re.compile(
    r"\b(error|fatal|critical|warn(?:ing)?|exception|traceback|panic|sigsegv|oom|refused|"
    r"timeout|timed out|failed|failure|rejected|exceeded|aborted|unavailable|5\d\d)\b")

# Hot path: str.translate runs in C, ~3x faster than a regex pass. Deleting every
# digit collapses timestamps, ids, sizes and latencies at once — exactly the
# grouping we want. UUIDs keep random letters, so they get a regex, but only on
# lines with 4+ hyphens (a cheap C-level prefilter).
_DIGITS = str.maketrans("", "", "0123456789")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

DENSITY_BUCKETS = 44
SERIES_CAP = 4096
MAX_TEMPLATES = 200_000
WINDOW = 15
PARALLEL_MIN_BYTES = 6 << 20       # below this, one process is faster than forking


def normalize(line):
    """Collapse a line to its grouping template (hot path — keep it C-heavy)."""
    if line.count("-") >= 4:
        line = _UUID.sub("<uuid>", line)
    return line.translate(_DIGITS).strip()


def _open(path, mode="rt"):
    """Open plain or gzipped logs transparently — rotated archives are .gz."""
    if path.endswith(".gz"):
        import gzip
        return gzip.open(path, mode, errors="replace")
    return open(path, mode, errors="replace")


def _decimate(pts, cap=SERIES_CAP):
    while len(pts) > cap:
        pts = pts[::2]
    return pts


def _scan_range(args):
    """Scan one byte range. Returns picklable aggregates only."""
    path, start, end, size, fmt, tpl_state = args
    miner = Drain.from_state(tpl_state) if tpl_state else None
    templates = {}
    series = defaultdict(list)
    dims_err, cand = defaultdict(Counter), defaultdict(set)
    density = [0] * DENSITY_BUCKETS
    total = signal = 0
    last_tpl = None

    with _open(path) as fh:
        if start:
            fh.seek(start - 1)
            fh.readline()                      # drop the partial first line
        pos = fh.tell()
        while pos < end:
            line = fh.readline()
            if not line:
                break
            here = pos
            pos += len(line)
            line = line.rstrip("\n")
            total += 1
            if not line.strip():
                continue
            line, _env = strip_container_envelope(line)
            if not line.strip():
                continue
            # Fold stack traces / indented continuations into the event above:
            # they are one event, not fifty.
            if is_continuation(line):
                if last_tpl is not None:
                    cont = templates.get(last_tpl)
                    if cont and cont[4] < 6:
                        cont[3] = (cont[3] + " | " + line.strip())[:300]
                        cont[4] += 1
                continue
            frac = here / size

            ts, level, msg, fields = parse_line(line, fmt)
            probe = f"{level or ''} {msg}"
            tpl = miner.match(probe) if miner else normalize(probe)
            last_tpl = tpl
            st = templates.get(tpl)
            if st is None:
                if len(templates) >= MAX_TEMPLATES:
                    continue
                st = templates[tpl] = [0, frac, here, line.strip()[:300], 0]  # count, frac, offset, sample, conts
            st[0] += 1

            sig = (level in ("ERROR", "ERR", "FATAL", "CRIT", "CRITICAL", "PANIC", "WARN", "WARNING")
                   if level else bool(SIGNAL_LOWER.search(probe.lower())))
            if sig:
                signal += 1
                density[min(int(frac * DENSITY_BUCKETS), DENSITY_BUCKETS - 1)] += 1
            # Structured fields first, then key=value pairs found in the text.
            pairs = list(fields.items()) + [(k, v) for k, v, _ in NUM_PAT.findall(line)]
            for k, v in pairs:
                sv = str(v)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    num = float(v)
                elif re.fullmatch(r"-?\d+(?:\.\d+)?", sv):
                    num = float(sv)
                else:
                    num = None
                if num is not None and k.lower() not in ("rid", "id", "txid", "commit", "status", "retry"):
                    ser = series[(k, "")]
                    ser.append(num)
                    if len(ser) >= SERIES_CAP * 2:
                        series[(k, "")] = ser[::2]
                if num is None or k.lower() in ("shard", "partition", "build", "instance"):
                    cand[k].add(sv[:40])
                    if sig:
                        dims_err[k][sv[:40]] += 1
            for dim, val in DIM_PAT.findall(line):
                cand[dim].add(val)
                if sig:
                    dims_err[dim][val] += 1

    return {"templates": templates, "series": {k: v for k, v in series.items()},
            "dims_err": {k: dict(v) for k, v in dims_err.items()},
            "dims_all": {k: list(v)[:200] for k, v in cand.items()},
            "density": density, "total": total, "signal": signal}


def _merge(parts):
    templates, series = {}, defaultdict(list)
    dims_err, dims_all = defaultdict(Counter), defaultdict(set)
    density = [0] * DENSITY_BUCKETS
    total = signal = 0
    for p in parts:                                   # parts stay in file order
        for tpl, rec in p["templates"].items():
            cnt, frac, off, sample = rec[0], rec[1], rec[2], rec[3]
            cur = templates.get(tpl)
            if cur is None:
                templates[tpl] = [cnt, frac, off, sample]
            else:
                cur[0] += cnt
                if frac < cur[1]:
                    cur[1], cur[2], cur[3] = frac, off, sample
        for k, pts in p["series"].items():
            series[k].extend(pts)
        for d, c in p["dims_err"].items():
            dims_err[d].update(c)
        for d, vals in p["dims_all"].items():
            dims_all[d].update(vals)
        density = [a + b for a, b in zip(density, p["density"])]
        total += p["total"]
        signal += p["signal"]
    series = {k: _decimate(v) for k, v in series.items()}
    return templates, series, dims_err, dims_all, density, total, signal


def _window_at(path, offset, before=WINDOW, after=WINDOW):
    """Fetch context lines around a byte offset without reading the whole file."""
    if offset is None:
        return []
    with _open(path) as fh:
        back = max(0, offset - 4000)
        fh.seek(back)
        if back:
            fh.readline()
        pre = deque(maxlen=before)
        while fh.tell() < offset:
            line = fh.readline()
            if not line:
                break
            pre.append(line.rstrip("\n"))
        out = list(pre)
        for _ in range(after):
            line = fh.readline()
            if not line:
                break
            out.append(line.rstrip("\n"))
    return out


def _tail(path, n=WINDOW * 2):
    size = os.path.getsize(path)
    with _open(path) as fh:
        fh.seek(max(0, size - 16000))
        return [l.rstrip("\n") for l in fh.readlines()[-n:]]


def spool_stdin(stream):
    """Buffer stdin to a temp file so it can be sized, chunked and seeked like any file."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    for chunk in iter(lambda: stream.read(1 << 20), ""):
        tmp.write(chunk)
    tmp.close()
    return tmp.name


TRAIN_LINES = 20_000


def _train_templates(path, fmt, n=TRAIN_LINES):
    """Learn line templates from a sample, then freeze them for the workers.

    Templates stabilize quickly, so a sample is enough — and a frozen model keeps
    the parallel scan cheap and deterministic.
    """
    miner = Drain()
    with _open(path) as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            line = line.rstrip("\n")
            line, _ = strip_container_envelope(line)
            if not line.strip() or is_continuation(line):
                continue
            _, level, msg, _ = parse_line(line, fmt)
            miner.train(f"{level or ''} {msg}")
    return miner.state()


def sniff_format(path, n=60):
    with _open(path) as fh:
        sample = [fh.readline() for _ in range(n)]
    return sniff([strip_container_envelope(l.rstrip("\n"))[0] for l in sample if l])


def scan(path, workers=None):
    """Scan a log file. Parallel across cores for large files, flat memory always."""
    tmp_unpacked = None
    if path.endswith(".gz"):
        # A gzip stream has no stable byte offsets, so unpack once and treat it
        # like any other file — keeps ranges, seeks and parallelism working.
        import gzip
        import shutil
        tmp = tempfile.NamedTemporaryFile("wb", suffix=".log", delete=False)
        with gzip.open(path, "rb") as src:
            shutil.copyfileobj(src, tmp)
        tmp.close()
        tmp_unpacked = path = tmp.name
    try:
        return _scan_file(path, workers)
    finally:
        if tmp_unpacked:
            os.unlink(tmp_unpacked)


def _scan_file(path, workers=None):
    size = max(os.path.getsize(path), 1)
    fmt = sniff_format(path)
    tpl_state = _train_templates(path, fmt)
    if workers is None:
        workers = max(1, (os.cpu_count() or 2) - 1)
    if size < PARALLEL_MIN_BYTES:
        workers = 1

    if workers == 1:
        parts = [_scan_range((path, 0, size, size, fmt, tpl_state))]
    else:
        step = size // workers
        ranges = [(path, i * step, size if i == workers - 1 else (i + 1) * step, size, fmt, tpl_state)
                  for i in range(workers)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_scan_range, ranges))

    templates, series, dims_err, dims_all, density, total, signal = _merge(parts)

    # Onset = earliest *new* signal-bearing template past the file's opening 3%.
    onset_frac, onset_off = None, None
    for tpl, (cnt, frac, off, sample) in templates.items():
        if frac > 0.03 and SIGNAL_LOWER.search(sample.lower()):
            if onset_frac is None or frac < onset_frac:
                onset_frac, onset_off = frac, off

    return {"path": path, "size": size, "workers": workers, "fmt": fmt, "total": total, "signal": signal,
            "templates": templates, "series": series, "dims_err": dims_err, "dims_all": dims_all,
            "density": density, "onset_frac": onset_frac,
            "onset_window": _window_at(path, onset_off), "tail_window": _tail(path)}


def build_pack(sc):
    """Turn raw scan aggregates into the evidence pack the model reads."""
    total = max(sc["total"], 1)
    templates, onset_frac = sc["templates"], sc["onset_frac"]

    sig_tpls = [(t, v) for t, v in templates.items() if SIGNAL_LOWER.search(v[3].lower())]
    patterns = []
    for tpl, (cnt, frac, off, sample) in sorted(sig_tpls, key=lambda kv: -kv[1][0])[:18]:
        note = ("PRESENT FROM FILE START — likely pre-existing baseline noise"
                if frac <= 0.03 else f"first appears at {round(frac*100)}% of file")
        patterns.append(f"{cnt:6d}x  [{note}]  {sample[:180]}")

    # Rare events: near-unique lines are candidate state changes, ranked by
    # rarity and by how closely they precede the first new error.
    rare_max = max(3, int(total * 0.002))
    scored = []
    for tpl, (cnt, frac, off, sample) in templates.items():
        if cnt > rare_max or not sample:
            continue
        score = 3.0 / (cnt + 1)
        if onset_frac is not None:
            gap = onset_frac - frac
            if 0 <= gap < 0.35:
                score += 3.0 * (1 - gap / 0.35)
            elif gap < 0:
                score += 0.4
        if CHANGE_PAT.search(sample):
            score += 1.5
        if SIGNAL_LOWER.search(sample.lower()):
            score -= 0.8
        scored.append((score, frac, cnt, sample))
    scored.sort(key=lambda x: -x[0])

    changes, change_pcts = [], []
    for _, frac, cnt, sample in scored[:18]:
        seen = f" (x{cnt} in file)" if cnt > 1 else ""
        rel = ""
        if onset_frac is not None:
            rel = " BEFORE first incident signal" if frac < onset_frac else " after incident started"
        changes.append(f"({round(frac*100)}% into file{seen}{rel}) {sample[:220]}")
        change_pcts.append(frac * 100)

    trends, trend_series = [], []
    for (key, unit), pts in sc["series"].items():
        if len(pts) < 12:
            continue
        q = max(len(pts) // 4, 1)
        head, tailv = sum(pts[:q]) / q, sum(pts[-q:]) / q
        if head == 0 and tailv == 0:
            continue
        ratio = (tailv + 1e-9) / (head + 1e-9)
        if ratio >= 1.5 or ratio <= 0.66:
            direction = "GREW" if ratio > 1 else "DROPPED"
            trends.append((abs(ratio if ratio > 1 else 1 / ratio),
                           f"{key}: {direction} {head:.1f}{unit} -> {tailv:.1f}{unit} "
                           f"(x{ratio:.1f}, {len(pts)} samples across file)",
                           (f"{key} {head:.0f}→{tailv:.0f}{unit}", pts, "up" if ratio > 1 else "down")))
    trends.sort(key=lambda x: -x[0])
    trend_series = [t[2] for t in trends[:12]]
    trends = [t[1] for t in trends[:12]]

    dim_notes = []
    for dim, cnt in sc["dims_err"].items():
        universe_size = len(sc["dims_all"].get(dim, []))
        if not cnt or not (2 <= universe_size <= 50):
            continue
        top, top_n = cnt.most_common(1)[0]
        share = top_n / sum(cnt.values())
        universe = set(sc["dims_all"].get(dim, []))
        if share > 0.7 and len(universe) > 1:
            healthy = sorted(universe - {top})[:4]
            others = (", ".join(v for v, _ in cnt.most_common()[1:4])
                      or f"none — {', '.join(healthy)} are error-free")
            dim_notes.append(f"{dim}: {round(share*100)}% of all error-like lines have {dim}={top} "
                             f"(other values: {others})")

    windows = ["\n".join(sc["onset_window"])]
    if sc["tail_window"]:
        windows.append("\n".join(sc["tail_window"]))

    return {"total_lines": sc["total"], "signal_lines": sc["signal"], "patterns": patterns,
            "changes": changes, "trends": trends, "dim_notes": dim_notes, "windows": windows,
            "density": sc["density"], "change_pcts": change_pcts, "trend_series": trend_series,
            "workers": sc["workers"], "fmt": sc["fmt"]}
