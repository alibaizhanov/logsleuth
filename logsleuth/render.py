"""Pretty terminal rendering for logsleuth reports. Pure stdlib ANSI + unicode."""
import re
import sys

SPARKS = "▁▂▃▄▅▆▇█"
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
CYAN, BLUE, YELLOW, GREEN, RED, MAGENTA, GREY = (
    "\033[36m", "\033[34m", "\033[33m", "\033[32m", "\033[31m", "\033[35m", "\033[90m")

SECTION_STYLE = [
    ("symptom", CYAN, "◉"), ("timeline", BLUE, "◷"), ("root cause", YELLOW, "⚑"),
    ("ruled out", MAGENTA, "⊘"), ("next steps", GREEN, "➤"), ("suggested", GREEN, "➤"),
]


def _bucket(values, width):
    if not values:
        return []
    n = len(values)
    out = []
    for b in range(width):
        lo, hi = b * n // width, max(b * n // width + 1, (b + 1) * n // width)
        chunk = values[lo:hi]
        out.append(sum(chunk) / len(chunk))
    return out


def sparkline(values, width=44):
    vals = _bucket(values, width)
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return "".join(SPARKS[min(int((v - lo) / span * 7.999), 7)] for v in vals)


def density_map(positions, total, width=44):
    counts = [0] * width
    for p in positions:
        counts[min(int(p / max(total, 1) * width), width - 1)] += 1
    return sparkline(counts, width)


def marker_row(change_pcts, width=44):
    row = [" "] * width
    for pct in change_pcts:
        row[min(int(pct / 100 * width), width - 1)] = "▼"
    return "".join(row)


def heat_color(line):
    """Color a sparkline char-by-char: low=grey, mid=yellow, high=red."""
    out = []
    for ch in line:
        i = SPARKS.find(ch)
        c = GREY if i < 2 else (YELLOW if i < 5 else RED)
        out.append(f"{c}{ch}")
    return "".join(out) + RESET


def _md_inline(text):
    text = re.sub(r"\*\*(.+?)\*\*", f"{BOLD}\\1{RESET}", text)
    text = re.sub(r"`([^`]+)`", f"{CYAN}\\1{RESET}", text)
    text = re.sub(r"\b[Cc]onfidence:?\s*\**\s*[Hh]igh\**", f"{BOLD}{GREEN} HIGH CONFIDENCE {RESET}", text)
    text = re.sub(r"\b[Cc]onfidence:?\s*\**\s*[Mm]edium\**", f"{BOLD}{YELLOW} MEDIUM CONFIDENCE {RESET}", text)
    text = re.sub(r"\b[Cc]onfidence:?\s*\**\s*[Ll]ow\**", f"{BOLD}{RED} LOW CONFIDENCE {RESET}", text)
    return text


def render_header(stats, model, width=76):
    """Everything computable BEFORE the model runs: frame, incident map, trends."""
    o = []
    bar = "─" * width
    o.append(f"{GREY}╭{bar}╮{RESET}")
    o.append(f"{GREY}│{RESET} {BOLD}logsleuth{RESET}  {DIM}· local analysis · nothing left this machine{RESET}")
    o.append(f"{GREY}│{RESET} {DIM}{stats['total_lines']:,} lines · {stats['signal_lines']:,} signal · "
             f"{len(stats.get('changes', []))} change events · model {model}{RESET}")
    o.append(f"{GREY}╰{bar}╯{RESET}")
    hist = stats.get("density") or []
    if any(hist):
        o.append("")
        o.append(f" {BOLD}INCIDENT MAP{RESET} {DIM}(error density across the file){RESET}")
        o.append(f"   {heat_color(sparkline(hist, len(hist)))}")
        pcts = stats.get("change_pcts") or []
        if pcts:
            o.append(f"   {MAGENTA}{marker_row(pcts)}{RESET}  {DIM}▼ = deploy/config/migration{RESET}")
        o.append(f"   {DIM}start{' ' * 34}end{RESET}")
    tseries = stats.get("trend_series") or []
    if tseries:
        o.append("")
        o.append(f" {BOLD}TRENDS{RESET}")
        for label, series, direction in tseries[:5]:
            arrow = f"{RED}▲{RESET}" if direction == "up" else f"{BLUE}▼{RESET}"
            o.append(f"   {arrow} {label:<28.28} {CYAN}{sparkline(series, 34)}{RESET}")
    o.append("")
    return "\n".join(o)


def colorize_md_line(raw, width=76):
    """Colorize one markdown line of the model report (for streaming)."""
    line = raw.rstrip()
    m = re.match(r"^#{2,3}\s+(.*)", line)
    if m:
        title = re.sub(r"\s*[—-].*$", "", m.group(1)).strip()
        color, icon = GREY, "•"
        for key, c, ic in SECTION_STYLE:
            if key in title.lower():
                color, icon = c, ic
                break
        return (f"\n {color}{BOLD}{icon} {title.upper()}{RESET}\n"
                f" {color}{'─' * min(len(title) + 4, width)}{RESET}")
    if line.strip().startswith(("- ", "* ")) or re.match(r"^\s*\d+\.\s", line):
        return f"   {_md_inline(line.strip())}"
    if line.strip():
        return f" {_md_inline(line.strip())}"
    return ""


def render_report(report_md, stats, model, elapsed, width=76):
    """stats: dict from preprocess() with extras: sig_positions, change_pcts, trend_series."""
    o = []
    bar = "─" * width

    # header
    o.append(f"{GREY}╭{bar}╮{RESET}")
    title = f" {BOLD}logsleuth{RESET}  {DIM}· local analysis · nothing left this machine{RESET}"
    o.append(f"{GREY}│{RESET}{title}")
    meta = (f" {DIM}{stats['total_lines']:,} lines · {stats['signal_lines']:,} signal · "
            f"{len(stats.get('changes', []))} change events · model {model} · {elapsed:.0f}s{RESET}")
    o.append(f"{GREY}│{RESET}{meta}")
    o.append(f"{GREY}╰{bar}╯{RESET}")

    # incident map
    pos = stats.get("sig_positions") or []
    if pos:
        o.append("")
        o.append(f" {BOLD}INCIDENT MAP{RESET} {DIM}(error density across the file){RESET}")
        strip = density_map(pos, stats["total_lines"])
        o.append(f"   {heat_color(strip)}")
        pcts = stats.get("change_pcts") or []
        if pcts:
            o.append(f"   {MAGENTA}{marker_row(pcts)}{RESET}  {DIM}▼ = deploy/config/migration{RESET}")
        o.append(f"   {DIM}start{' ' * 34}end{RESET}")

    # trends
    tseries = stats.get("trend_series") or []
    if tseries:
        o.append("")
        o.append(f" {BOLD}TRENDS{RESET}")
        for label, series, direction in tseries[:5]:
            arrow = f"{RED}▲{RESET}" if direction == "up" else f"{BLUE}▼{RESET}"
            o.append(f"   {arrow} {label:<28.28} {CYAN}{sparkline(series, 34)}{RESET}")

    # model report
    for raw in report_md.splitlines():
        line = raw.rstrip()
        m = re.match(r"^#{2,3}\s+(.*)", line)
        if m:
            title = re.sub(r"\s*[—-].*$", "", m.group(1)).strip()
            color, icon = GREY, "•"
            for key, c, ic in SECTION_STYLE:
                if key in title.lower():
                    color, icon = c, ic
                    break
            o.append("")
            o.append(f" {color}{BOLD}{icon} {title.upper()}{RESET}")
            o.append(f" {color}{'─' * min(len(title) + 4, width)}{RESET}")
        elif line.strip().startswith(("- ", "* ")) or re.match(r"^\s*\d+\.\s", line):
            o.append(f"   {_md_inline(line.strip())}")
        elif line.strip():
            o.append(f" {_md_inline(line.strip())}")
    o.append("")
    return "\n".join(o)


def supports_pretty(force_plain=False):
    import os
    if force_plain or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()
