"""Structure-preserving redaction and a content-free health check.

logsleuth never sees your logs — which also means we can't debug why it did badly
on yours. These two commands close that loop without leaking anything:

  --redact   rewrite a log so its *shape* survives and its *content* does not,
             producing a file you can attach to a bug report.
  --health   print parse statistics only (counts, rates, template shapes) so a
             maintainer can tell which assumption broke, with zero log content.

Redaction rule of thumb: a word that occurs many times in a file is system
vocabulary ("timeout", "connection", "pool"); a rare word is far more likely to
be an identifier, a hostname, a customer name. Frequent words stay, rare words go.
"""
import re
from collections import Counter

from .parse import parse_line, sniff
from .scan import sniff_format

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
IPV6 = re.compile(r"\b(?:[0-9a-f]{1,4}:){2,}[0-9a-f]{1,4}\b", re.I)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
LONGHEX = re.compile(r"\b[0-9a-f]{16,}\b", re.I)
B64 = re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")
PATH = re.compile(r"(/[\w.\-@+]+){2,}/?")
URL = re.compile(r"\b[a-z]+://[^\s\"']+", re.I)
QUOTED = re.compile(r"\"([^\"]{3,})\"|'([^']{3,})'")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{2,}")
NUM = re.compile(r"\d+")

KEEP_ALWAYS = {
    "error", "warn", "warning", "info", "debug", "fatal", "critical", "trace",
    "exception", "timeout", "failed", "failure", "refused", "connection", "pool",
    "true", "false", "null", "none", "and", "the", "for", "with", "from", "not",
}
MIN_WORD_FREQ = 20          # below this, a word is treated as an identifier


def build_vocabulary(path, min_freq=MIN_WORD_FREQ):
    """Words frequent enough to be system vocabulary rather than data."""
    counts = Counter()
    with open(path, errors="replace") as fh:
        for line in fh:
            counts.update(w.lower() for w in WORD.findall(line))
    return {w for w, c in counts.items() if c >= min_freq} | KEEP_ALWAYS


def redact_line(line, vocab):
    line = URL.sub("<url>", line)
    line = EMAIL.sub("<email>", line)
    line = UUID.sub("<uuid>", line)
    line = IPV4.sub("<ip>", line)
    line = IPV6.sub("<ip6>", line)
    line = LONGHEX.sub("<hex>", line)
    line = B64.sub("<b64>", line)
    line = PATH.sub(lambda m: "/" + "/".join("<seg>" for _ in m.group(0).strip("/").split("/")), line)
    line = QUOTED.sub('"<text>"', line)
    line = WORD.sub(lambda m: m.group(0) if m.group(0).lower() in vocab else "<w>", line)
    # keep magnitude, drop the value: 4096 -> 9999, 7 -> 9
    line = NUM.sub(lambda m: "9" * len(m.group(0)), line)
    return line


def redact_file(path, out, min_freq=MIN_WORD_FREQ):
    vocab = build_vocabulary(path, min_freq)
    kept = redacted = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            ts_head = ""
            # keep timestamps intact: they carry ordering, not secrets
            m = re.match(r"^(\[?[\d\-/:T. +]{8,32}\]?)", line)
            if m:
                ts_head, line = m.group(1), line[m.end():]
            safe = redact_line(line.rstrip("\n"), vocab)
            kept += len(re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{2,}", safe))
            redacted += safe.count("<w>")
            out.write(ts_head + safe + "\n")
    return {"vocab_size": len(vocab), "words_kept": kept, "words_redacted": redacted}


def health(path):
    """Content-free diagnostics: are our parsing assumptions holding on this file?"""
    fmt = sniff_format(path)
    total = ts_ok = cont = 0
    levels = Counter()
    shapes = Counter()
    with open(path, errors="replace") as fh:
        for i, line in enumerate(fh):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            total += 1
            ts, level, msg, fields = parse_line(line, fmt)
            if ts:
                ts_ok += 1
            if level:
                levels[level] += 1
            if total <= 20000:
                # character-class skeleton: shows format, reveals no content
                sk = re.sub(r"[A-Za-z]+", "A", line[:80])
                sk = re.sub(r"\d+", "9", sk)
                shapes[re.sub(r"\s+", " ", sk)] += 1
    return {"format": fmt, "lines": total,
            "timestamp_rate": round(100 * ts_ok / max(total, 1)),
            "level_rate": round(100 * sum(levels.values()) / max(total, 1)),
            "levels": dict(levels.most_common(6)),
            "top_shapes": shapes.most_common(5)}


def format_health(h, scan_stats=None):
    out = [f"format detected      {h['format']}",
           f"lines                {h['lines']:,}",
           f"timestamps parsed    {h['timestamp_rate']}%",
           f"levels detected      {h['level_rate']}%  {h['levels'] or ''}"]
    if scan_stats:
        out += [f"templates            {scan_stats['templates']:,} "
                f"(compression {scan_stats['compression']:.0f}x)",
                f"signal lines         {scan_stats['signal']:,}",
                f"rare events found    {scan_stats['rare']}",
                f"trends found         {scan_stats['trends']}"]
    out.append("line shapes (letters->A, digits->9, no content):")
    for sk, n in h["top_shapes"]:
        out.append(f"  {n:7,}x  {sk[:70]}")
    warn = []
    if h["timestamp_rate"] < 50:
        warn.append("! few timestamps parsed — ordering and onset detection will be weak")
    if scan_stats and scan_stats["compression"] < 2:
        warn.append("! templates barely compress — dedup is not grouping your lines")
    if scan_stats and scan_stats["rare"] == 0:
        warn.append("! no rare events — state changes may be missing from the evidence")
    return "\n".join(out + ([""] + warn if warn else []))
