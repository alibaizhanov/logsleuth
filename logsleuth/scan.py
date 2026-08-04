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
PARALLEL_MIN_BYTES = 32 << 20      # below this, one process is faster than forking


def normalize(line):
    """Collapse a line to its grouping template (hot path — keep it C-heavy)."""
    if line.count("-") >= 4:
        line = _UUID.sub("<uuid>", line)
    return line.translate(_DIGITS).strip()


def _decimate(pts, cap=SERIES_CAP):
    while len(pts) > cap:
        pts = pts[::2]
    return pts


def _scan_range(args):
    """Scan one byte range. Returns picklable aggregates only."""
    path, start, end, size = args
    templates = {}
    series = defaultdict(list)
    dims_err, dims_all = defaultdict(Counter), defaultdict(set)
    density = [0] * DENSITY_BUCKETS
    total = signal = 0

    with open(path, errors="replace") as fh:
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
            frac = here / size

            tpl = normalize(line)
            st = templates.get(tpl)
            if st is None:
                if len(templates) >= MAX_TEMPLATES:
                    continue
                st = templates[tpl] = [0, frac, here, line.strip()[:300]]   # count, first_frac, offset, sample
            st[0] += 1

            if SIGNAL_LOWER.search(line.lower()):
                signal += 1
                density[min(int(frac * DENSITY_BUCKETS), DENSITY_BUCKETS - 1)] += 1
                for dim, val in DIM_PAT.findall(line):
                    dims_err[dim][val] += 1
                    dims_all[dim].add(val)
            else:
                for dim, val in DIM_PAT.findall(line):
                    dims_all[dim].add(val)

            for key, val, unit in NUM_PAT.findall(line):
                if key.lower() not in ("rid", "id", "txid", "commit", "status", "retry"):
                    s = series[(key, unit)]
                    s.append(float(val))
                    if len(s) >= SERIES_CAP * 2:
                        series[(key, unit)] = s[::2]

    return {"templates": templates, "series": {k: v for k, v in series.items()},
            "dims_err": {k: dict(v) for k, v in dims_err.items()},
            "dims_all": {k: list(v) for k, v in dims_all.items()},
            "density": density, "total": total, "signal": signal}


def _merge(parts):
    templates, series = {}, defaultdict(list)
    dims_err, dims_all = defaultdict(Counter), defaultdict(set)
    density = [0] * DENSITY_BUCKETS
    total = signal = 0
    for p in parts:                                   # parts stay in file order
        for tpl, (cnt, frac, off, sample) in p["templates"].items():
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
    with open(path, errors="replace") as fh:
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
    with open(path, errors="replace") as fh:
        fh.seek(max(0, size - 16000))
        return [l.rstrip("\n") for l in fh.readlines()[-n:]]


def spool_stdin(stream):
    """Buffer stdin to a temp file so it can be sized, chunked and seeked like any file."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    for chunk in iter(lambda: stream.read(1 << 20), ""):
        tmp.write(chunk)
    tmp.close()
    return tmp.name


def scan(path, workers=None):
    """Scan a log file. Parallel across cores for large files, flat memory always."""
    size = max(os.path.getsize(path), 1)
    if workers is None:
        workers = max(1, (os.cpu_count() or 2) - 1)
    if size < PARALLEL_MIN_BYTES:
        workers = 1

    if workers == 1:
        parts = [_scan_range((path, 0, size, size))]
    else:
        step = size // workers
        ranges = [(path, i * step, size if i == workers - 1 else (i + 1) * step, size)
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

    return {"path": path, "size": size, "workers": workers, "total": total, "signal": signal,
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
        if not cnt:
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
            "workers": sc["workers"]}
