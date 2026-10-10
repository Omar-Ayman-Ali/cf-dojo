"""dojo report — one self-contained HTML page: rating, activity, verdicts, weak tags, today's plan.

The page has no external resources (inline CSS and SVG, no scripts), follows the system's light
or dark theme, and is rewritten on every run at <data dir>/report.html.
"""
from __future__ import annotations

import datetime as dt
import html
import math
import os
import re
import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path
from typing import Iterable, Sequence

from dojo import paths
from dojo.cf import analysis, metrics, recommend
from dojo.cf.model import VERDICT_SHORT, RatingChange
from dojo.cf.snapshot import Snapshot
from dojo.cf.upsolve import contests_taken, upsolve_queue
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.state import State
from dojo.term import RANKS, rank_of
from dojo.timeutil import fmt_day, fmt_when, week_start

HEAT_WEEKS = 26                     # ~6 months of daily activity
WEEKS = 12
TAGS_SHOWN = 14
HEAT_LEVELS = (1, 2, 3, 5)          # first-AC counts where heat levels 1..4 start

DESCRIPTION = """\
Write an HTML dashboard to your data directory and print its path: rating history with rank
bands, progress to your target, weekly solves, a 6-month activity heatmap, verdict profile,
weak tags, today's plan and the upsolve queue. One file, no internet needed to view it."""


def register(sub, common):
    p = add_command(sub, common, "report", "write an HTML dashboard", description=DESCRIPTION)
    p.add_argument("--open", action="store_true", help="open it in your browser (xdg-open)")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    snap = ctx.snapshot()
    snap.require("status")
    page = build_report(snap, ctx.state)
    path = paths.ensure(paths.data_dir()) / "report.html"
    _write(path, page)
    ctx.term.out(str(path))
    if ctx.args.open:
        open_in_browser(path)
    return 0


def _write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".report.", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def open_in_browser(path: Path) -> None:
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    elif not webbrowser.open(path.as_uri()):
        raise DojoError(f"couldn't find a browser to open it — open {path} yourself")


# ---- page --------------------------------------------------------------------------------

def build_report(snap: Snapshot, state: State) -> str:
    """The whole page as a string. Creates today's plan in `state` if there isn't one yet."""
    ov = analysis.overview(snap)
    sections = [
        _header(ov, snap),
        _tiles(ov),
        _card("Rating", _rating_section(ov, snap), wide=True),
        _card(f"Solved per week · last {WEEKS} weeks", _weekly_chart(ov.weekly, ov.week_goal)),
        _card("Activity · last 6 months", _heatmap(snap)),
        _card("Verdicts", _verdicts(ov)),
        _card("Insights", _insights(ov)),
        _card("Tags to practise", _tags(snap), wide=True),
        _card("Today's plan", _plan(snap, state)),
        _card("Upsolve", _upsolve(snap, ov.comfort)),
    ]
    title = f"dojo · {ov.handle}"
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="color-scheme" content="light dark">\n'
            f"<title>{_e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
            + "\n".join(sections)
            + f'\n<footer>Generated {_e(fmt_when(snap.now))} by <code>dojo report</code> · '
              f"data as of {_e(_data_age(snap))}</footer>\n</main>\n</body>\n</html>\n")


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _a(text: str, url: str | None) -> str:
    """A link that opens in a new tab; only http(s) URLs become links."""
    if not url or not re.match(r"https?://", url):
        return _e(text)
    return f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(text)}</a>'


def _code(text: str) -> str:
    """Escape, then turn `dojo today` into <code>dojo today</code>."""
    return re.sub(r"`([^`]*)`", r"<code>\1</code>", _e(text))


def _card(title: str, body: str, *, wide: bool = False) -> str:
    cls = "card wide" if wide else "card"
    return f'<section class="{cls}">\n<h2>{_e(title)}</h2>\n{body}\n</section>'


def _rank_chip(rating: int | None, text: object | None = None) -> str:
    """A rating with a dot in its rank colour (the number itself stays in text ink for contrast)."""
    shown = text if text is not None else ("unrated" if rating is None else rating)
    name, colour = rank_of(rating)
    return (f'<span class="chip" title="{_e(name.title())}"><i style="background:{colour}"></i>'
            f"{_e(shown)}</span>")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _data_age(snap: Snapshot) -> str:
    at = snap.fetched_at.get("status")
    return fmt_when(dt.datetime.fromtimestamp(at, snap.tz)) if at else "unknown"


def _header(ov: analysis.Overview, snap: Snapshot) -> str:
    rank = "unrated" if ov.rating is None else ov.rank.title()
    sub = [rank, f"comfort {ov.comfort}", f"target {ov.target}"]
    if not ov.authenticated:
        sub.append("public submissions only")
    return (f'<header>\n<h1>{_rank_chip(ov.rating, ov.handle)}</h1>\n'
            f'<p class="muted">{" · ".join(_e(s) for s in sub)} · {_e(fmt_day(snap.today))}</p>\n</header>')


def _tile(label: str, value: str, note: str = "") -> str:
    return (f'<div class="tile"><div class="label">{_e(label)}</div><div class="value">{value}</div>'
            + (f'<div class="note">{note}</div>' if note else "") + "</div>")


def _tiles(ov: analysis.Overview) -> str:
    if ov.rating is None:
        rating = _tile("Rating", "unrated", _e("a rated round sets it"))
        gap = _tile("To target", _e(ov.target), _e(analysis.target_name(ov.target)))
    else:
        rating = _tile("Rating", _rank_chip(ov.rating),
                       _e(f"max {ov.max_rating} · {_plural(ov.contests, 'rated round')}"))
        left = max(0, ov.to_target or 0)
        gap = _tile("To target", _e(left) if left else "reached",
                    _e(f"{ov.target} ({analysis.target_name(ov.target)})"))
    if ov.last_ac is None:
        last = "no AC yet"
    else:
        n = ((ov.as_of.date() if ov.as_of else dt.date.today()) - ov.last_ac.date()).days
        last = "last AC " + ("today" if n <= 0 else "yesterday" if n == 1 else f"{n} days ago")
    tiles = [
        rating, gap,
        _tile("Solved", _e(ov.solved_total), _e(f"{ov.solved_problemset} problemset · {ov.solved_groups} groups")),
        _tile("This week", _e(f"{ov.week_solved}/{ov.week_goal}"), _e(f"since {fmt_day(ov.week_start)}")),
        _tile("Streak", _e(_plural(ov.streak, "day")), _e(f"best {ov.best_streak} · {last}")),
        _tile("Comfort", _rank_chip(ov.comfort), "the rating you solve reliably"),
    ]
    return '<div class="tiles">\n' + "\n".join(tiles) + "\n</div>"


# ---- rating ------------------------------------------------------------------------------

def _nice_step(span: float, max_ticks: int = 6) -> int:
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if span / step <= max_ticks:
            return step
    return 10 ** math.ceil(math.log10(max(span, 1)))


def _progress(ov: analysis.Overview) -> str:
    if ov.rating is None:
        return f'<p class="muted">Unrated · target {_e(ov.target)} ({_e(analysis.target_name(ov.target))}).</p>'
    frac = max(0.0, min(1.0, ov.rating / ov.target)) if ov.target > 0 else 1.0
    left = ov.to_target if ov.to_target and ov.to_target > 0 else 0
    text = f"{left} to {analysis.target_name(ov.target)}" if left else "target reached"
    return (f'<div class="progress" role="img" aria-label="{_e(f"rating {ov.rating} of {ov.target}")}">'
            f'<div class="meter"><span style="width:{frac * 100:.1f}%"></span></div>'
            f'<div class="meter-labels"><span>{_e(ov.rating)}</span><strong>{_e(text)}</strong>'
            f"<span>{_e(ov.target)}</span></div></div>")


def _rating_section(ov: analysis.Overview, snap: Snapshot) -> str:
    out = [_progress(ov)]
    hist = ov.rating_history
    if not hist:
        out.append('<p class="muted">No rated rounds yet — a Div. 3 or Div. 4 round sets your rating '
                   "(<code>dojo contests</code>).</p>")
        return "\n".join(out)
    out.append(_rating_chart(hist, ov.target, snap))
    rows = [[_e(dt.datetime.fromtimestamp(r.time, snap.tz).strftime("%d %b %Y")),
             _a(r.contest_name, snap.contest_url(r.contest_id)), _e(f"#{r.rank}"),
             f'<span class="{"up" if r.delta >= 0 else "down"}">{_e(f"{r.delta:+d}")}</span>',
             _rank_chip(r.new)] for r in reversed(hist)]
    out.append(_table(["Date", "Round", "Rank", "Δ", "Rating"], rows, "lwrrr"))
    return "\n".join(out)


def _rating_chart(hist: Sequence[RatingChange], target: int, snap: Snapshot) -> str:
    W, H, L, R, T, B = 1000, 300, 48, 86, 14, 30
    pw, ph = W - L - R, H - T - B
    values = [r.new for r in hist]
    lo = max(0, (min(values) - 100) // 100 * 100)
    hi = (max(max(values), target) + 100 + 99) // 100 * 100
    t0, t1 = hist[0].time, hist[-1].time

    def x(t: int) -> float:
        return L + (pw / 2 if t1 == t0 else (t - t0) / (t1 - t0) * pw)

    def y(v: float) -> float:
        return T + ph - (v - lo) / (hi - lo) * ph

    parts = [f'<div class="scroll"><svg viewBox="0 0 {W} {H}" class="chart rating" role="img" '
             f'aria-label="{_e(f"Rating history: {len(hist)} rated rounds, now {values[-1]}")}">']
    # rank bands, lowest first
    bands = sorted(RANKS, key=lambda r: r[0])
    for i, (low, name, colour) in enumerate(bands):
        top = bands[i + 1][0] if i + 1 < len(bands) else 10 ** 6
        a, b = max(low, lo), min(top, hi)
        if a >= b:
            continue
        parts.append(f'<rect x="{L}" y="{y(b):.1f}" width="{pw}" height="{y(a) - y(b):.1f}" '
                     f'fill="{colour}" class="band"><title>{_e(name.title())}: {a}–{top - 1}</title></rect>')
        if y(a) - y(b) >= 14:
            parts.append(f'<text x="{L + pw + 8}" y="{(y(a) + y(b)) / 2 + 4:.1f}" class="band-label">'
                         f"{_e(name.title())}</text>")
    step = _nice_step(hi - lo)
    v = (lo + step - 1) // step * step
    while v <= hi:
        parts.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{L - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v}</text>')
        v += step
    if lo <= target <= hi:
        parts.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(target):.1f}" y2="{y(target):.1f}" class="target"/>'
                     f'<text x="{L + 4}" y="{y(target) - 5:.1f}" class="tick">target {target}</text>')
    pts = " ".join(f"{x(r.time):.1f},{y(r.new):.1f}" for r in hist)
    parts.append(f'<polyline points="{pts}" class="line"/>')
    for r in hist:
        when = dt.datetime.fromtimestamp(r.time, snap.tz)
        tip = f"{r.contest_name}\n{when:%d %b %Y} · rank #{r.rank}\n{r.old} → {r.new} ({r.delta:+d})"
        parts.append(f'<g class="pt"><circle cx="{x(r.time):.1f}" cy="{y(r.new):.1f}" r="12" class="hit"/>'
                     f'<circle cx="{x(r.time):.1f}" cy="{y(r.new):.1f}" r="4.5" class="dot"/>'
                     f"<title>{_e(tip)}</title></g>")
    last = hist[-1]
    parts.append(f'<text x="{x(last.time) + (8 if len(hist) == 1 else -8):.1f}" y="{y(last.new) - 10:.1f}" '
                 f'class="value" text-anchor="{"start" if len(hist) == 1 else "end"}">{last.new}</text>')
    # x labels: every round when there are few, else first, middle and last
    idx = range(len(hist)) if len(hist) <= 6 else sorted({0, len(hist) // 2, len(hist) - 1})
    for i in idx:
        r = hist[i]
        anchor = "middle" if len(hist) == 1 else "start" if i == 0 else "end" if i == len(hist) - 1 else "middle"
        parts.append(f'<text x="{x(r.time):.1f}" y="{H - 10}" class="tick" text-anchor="{anchor}">'
                     f"{dt.datetime.fromtimestamp(r.time, snap.tz):%b %Y}</text>")
    parts.append("</svg></div>")
    return "".join(parts)


# ---- weekly and daily activity -----------------------------------------------------------

def _weekly_chart(weekly: Sequence[tuple[dt.date, int]], goal: int) -> str:
    if not weekly:
        return '<p class="muted">No weeks to show.</p>'
    W, H, L, R, T, B = 520, 210, 30, 8, 18, 30
    pw, ph = W - L - R, H - T - B
    counts = [n for _, n in weekly]
    top = max(max(counts), goal if goal > 0 else 0, 1)
    step = _nice_step(top, 5)
    hi = math.ceil(top / step) * step

    def y(v: float) -> float:
        return T + ph - v / hi * ph

    slot = pw / len(weekly)
    bw = min(28.0, slot * 0.62)
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="{_e(f"Problems solved per week, last {len(weekly)} weeks: " + ", ".join(map(str, counts)))}">']
    v = 0
    while v <= hi:
        parts.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="{"axis" if v == 0 else "grid"}"/>'
                     f'<text x="{L - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v}</text>')
        v += step
    if goal > 0:
        parts.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(goal):.1f}" y2="{y(goal):.1f}" class="target"/>'
                     f'<text x="{L + pw}" y="{y(goal) - 5:.1f}" class="tick" text-anchor="end">goal {goal}</text>')
    peak = max(range(len(counts)), key=lambda i: (counts[i], i))
    for i, (start, n) in enumerate(weekly):
        cx = L + slot * i + slot / 2
        x0 = cx - bw / 2
        tip = f"week of {fmt_day(start)}: {_plural(n, 'problem')}"
        hit = f'<rect x="{L + slot * i:.1f}" y="{T}" width="{slot:.1f}" height="{ph}" class="hit"/>'
        bar = _bar_path(x0, y(0), bw, y(0) - y(n)) if n else ""
        label = ""
        if n and (i == peak or i == len(weekly) - 1):
            label = f'<text x="{cx:.1f}" y="{y(n) - 6:.1f}" class="value" text-anchor="middle">{n}</text>'
        parts.append(f'<g class="pt">{hit}{bar}{label}<title>{_e(tip)}</title></g>')
        parts.append(f'<text x="{cx:.1f}" y="{H - 10}" class="tick" text-anchor="middle">{start:%d %b}</text>')
    parts.append("</svg>")
    total = sum(counts)
    return "".join(parts) + (f'<p class="muted">{_e(_plural(total, "problem"))} in {len(weekly)} weeks · '
                             f'weekly goal {_e(goal)} · weeks start on {weekly[-1][0]:%A}s.</p>')


def _bar_path(x: float, base: float, w: float, h: float, r: float = 4.0) -> str:
    """A bar with its data end (top) rounded and its baseline square."""
    r = min(r, w / 2, h)
    top = base - h
    return (f'<path class="bar" d="M{x:.1f},{base:.1f} V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} '
            f'H{x + w - r:.1f} Q{x + w:.1f},{top:.1f} {x + w:.1f},{top + r:.1f} V{base:.1f} Z"/>')


def heat_level(n: int) -> int:
    """0 for no solves, else 1..4 by HEAT_LEVELS."""
    return sum(n >= t for t in HEAT_LEVELS)


def _heatmap(snap: Snapshot) -> str:
    today = snap.today
    first = week_start(today, snap.cfg.week_start_day) - dt.timedelta(weeks=HEAT_WEEKS - 1)
    days = metrics.daily_counts(snap, (today - first).days + 1)
    cell, gap, L, T = 13, 3, 34, 18
    cols = HEAT_WEEKS
    W, H = L + cols * (cell + gap), T + 7 * (cell + gap) + 4
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart heat" role="img" '
             f'aria-label="{_e("Problems first solved per day over the last 6 months")}">']
    for row in range(7):
        if row % 2 == 0:
            name = (first + dt.timedelta(days=row)).strftime("%a")
            parts.append(f'<text x="{L - 6}" y="{T + row * (cell + gap) + cell - 2}" class="tick" '
                         f'text-anchor="end">{name}</text>')
    seen_month = None
    for day, n in days:
        col, row = (day - first).days // 7, (day - first).days % 7
        x, yy = L + col * (cell + gap), T + row * (cell + gap)
        if row == 0 and day.month != seen_month and col < cols - 1:
            seen_month = day.month
            parts.append(f'<text x="{x}" y="{T - 6}" class="tick">{day:%b}</text>')
        tip = f"{fmt_day(day)}: {_plural(n, 'problem')}"
        parts.append(f'<rect x="{x}" y="{yy}" width="{cell}" height="{cell}" rx="2" class="h{heat_level(n)}">'
                     f"<title>{_e(tip)}</title></rect>")
    parts.append("</svg>")
    total, active = sum(n for _, n in days), sum(1 for _, n in days if n)
    legend = "".join(f'<i class="h{i}"></i>' for i in range(5))
    labels = ["0", "1", "2", "3–4", "5+"]
    return ("".join(parts) + f'<div class="heat-legend"><span>{_e(_plural(total, "problem"))} on '
            f'{_e(_plural(active, "day"))}</span><span class="scale">less {legend} more</span></div>'
            f'<p class="muted small">Cells: {" · ".join(labels)} first ACs that day.</p>')


# ---- verdicts, insights, tags --------------------------------------------------------------

def _verdicts(ov: analysis.Overview) -> str:
    total = sum(ov.verdicts.values())
    if not total:
        return '<p class="muted">No submissions yet.</p>'
    rows = []
    top = max(ov.verdicts.values())
    for v, n in sorted(ov.verdicts.items(), key=lambda x: (-x[1], x[0])):
        short = VERDICT_SHORT.get(v, v)
        rows.append([f'<span title="{_e(v)}">{_e(short)}</span>', _e(n), _e(f"{n / total:.0%}"),
                     f'<span class="hbar"><span style="width:{n / top * 100:.1f}%"></span></span>'])
    stats = [_tile("WA per AC", _e(f"{ov.wa_per_ac:.2f}"), _e(f"{ov.verdicts['WRONG_ANSWER']} WA · {ov.verdicts['OK']} AC")),
             _tile("First try", _e(f"{ov.first_try_rate:.0%}"), "solved with no failed attempt")]
    return ('<div class="tiles mini">' + "".join(stats) + "</div>"
            + _table(["Verdict", "Count", "Share", ""], rows, "lrrl")
            + f'<p class="muted small">{_e(_plural(total, "submission"))}.</p>')


def _insights(ov: analysis.Overview) -> str:
    if not ov.insights:
        return '<p class="muted">Nothing stands out — keep going.</p>'
    return '<ul class="insights">' + "".join(f"<li>{_code(i.text)}</li>" for i in ov.insights) + "</ul>"


def _tags(snap: Snapshot) -> str:
    if "problemset" not in snap.loaded:
        return '<p class="muted">No problemset data — run <code>dojo sync</code> while online.</p>'
    rep = analysis.tag_report(snap)
    if not rep.pool:
        return (f'<p class="muted">No problemset problems rated {rep.low}–{rep.high} from contest '
                f"{snap.cfg.min_contest_id} on.</p>")
    focus = analysis.top_focus(rep.tags)
    shown = [s for s in rep.tags if s.importance >= analysis.SHOW_MIN_IMPORTANCE][:TAGS_SHOWN]
    top = max((s.focus for s in shown), default=0.0) or 1.0
    rows = []
    for s in shown:
        fail = f"{s.failed_attempts / s.attempts:.0%} of {s.attempts}" if s.attempts else "—"
        mark = ' class="focus"' if s.tag in focus else ""
        rows.append([f"<span{mark}>{_e(s.tag)}</span>", _e(f"{s.importance:.0%}"), _e(s.solved),
                     _e(f"{s.expected:.1f}"), _e(fail),
                     f'<span class="hbar"><span style="width:{s.focus / top * 100:.1f}%"></span></span>'])
    out = []
    if focus:
        out.append(f"<p>Focus next: <strong>{_e(', '.join(focus))}</strong>.</p>")
    out.append(_table(["Tag", "Share", "Solved", "Expected", "Fail rate", "Focus"], rows, "lrrrrl"))
    notes = [f"Rated {rep.low}–{rep.high}. Share: of the {rep.pool} problemset problems in that band "
             f"(contest {snap.cfg.min_contest_id}+), how many carry the tag. Expected: share × your "
             f"{rep.tagged_solved} tagged solves in the band."]
    if rep.untagged_solved:
        notes.append(f"{rep.untagged_solved} of your {rep.solved_total} solved problems have no tags "
                     f"(mostly group problems), so they aren't counted.")
    out.append("".join(f'<p class="muted small">{_e(n)}</p>' for n in notes))
    return "\n".join(out)


# ---- plan and upsolve ----------------------------------------------------------------------

def _plan(snap: Snapshot, state: State) -> str:
    try:
        plan = recommend.todays_plan(snap, state)
    except DojoError as e:
        return f'<p class="muted">{_e(e)}</p>'
    if not plan.items:
        return '<p class="muted">Nothing fits today — try <code>dojo upsolve</code> or <code>dojo retry</code>.</p>'
    show_tags = not snap.cfg.hide_tags
    rows = []
    done = 0
    for it in plan.items:
        ok = recommend.item_done(snap, it, day=plan.day)
        done += ok
        p = snap.problem(it.key)
        name = f"{it.key} {p.name}".rstrip()
        note = recommend.item_note(snap, it, plan.day)
        if show_tags and p.tags:
            note = (note + " · " if note else "") + ", ".join(p.tags)
        rows.append([f'<span class="{"done" if ok else "todo"}">{"✓" if ok else "○"}</span>',
                     _e(recommend.slot_label(snap, it, plan.day)), _a(name, snap.url(it.key)),
                     _rank_chip(it.rating) if it.rating else '<span class="muted">—</span>',
                     f'<span class="muted">{_e(note)}</span>'])
    head = (f'<p><strong>{done}/{len(plan.items)} done</strong> <span class="muted">· '
            f"{_e(fmt_day(plan.day))} · comfort {plan.comfort}</span></p>")
    return head + _table(["", "Slot", "Problem", "Rating", ""], rows, "llwrw") + (
        '<p class="muted small">Swap one: <code>dojo skip &lt;id&gt;</code> · new set: '
        "<code>dojo today --reroll</code></p>")


def _upsolve(snap: Snapshot, comfort: int) -> str:
    if "problemset" not in snap.loaded:
        return '<p class="muted">No problemset data — run <code>dojo sync</code> while online.</p>'
    items = upsolve_queue(snap, comfort)
    if not items:
        return '<p class="muted">Nothing to upsolve from your contests.</p>'
    taken = contests_taken(snap)
    rated = {r.contest_id: r for r in snap.rating_history}
    out = [f'<p class="muted">{_e(_plural(len(items), "problem"))} rated up to {comfort + 500}, '
           f"newest contest first.</p>"]
    cid = None
    rows: list[list[str]] = []

    def flush() -> None:
        if rows:
            out.append(_table(["Problem", "Rating", ""], rows, "wrl"))
            rows.clear()

    for u in items:
        if u.contest_id != cid:
            flush()
            cid = u.contest_id
            bits = [fmt_day(snap.local_date(taken[cid][0]))] if cid in taken else []
            r = rated.get(cid)
            if r:
                bits += [f"rank {r.rank}", f"{r.delta:+d}"]
            out.append(f"<h3>{_a(u.contest_name, snap.contest_url(cid))} "
                       f'<span class="muted">{_e(" · ".join(bits))}</span></h3>')
        name = f"{u.key} {snap.problem(u.key).name}".rstrip()
        rows.append([_a(name, snap.url(u.key)),
                     _rank_chip(u.rating) if u.rating else '<span class="muted">unrated</span>',
                     '<span class="muted">tried in contest</span>' if u.attempted else ""])
    flush()
    return "\n".join(out)


def _table(header: Sequence[str], rows: Iterable[Sequence[str]], align: str = "") -> str:
    """Cells are already-escaped HTML. `align`: one letter per column: l (left), r (right,
    numeric) or w (left, may wrap); other cells stay on one line."""
    def cls(i: int) -> str:
        a = align[i] if i < len(align) else "l"
        return ' class="num"' if a == "r" else ' class="wrap"' if a == "w" else ""
    head = "".join(f"<th{cls(i)}>{_e(h)}</th>" for i, h in enumerate(header))
    body = "".join("<tr>" + "".join(f"<td{cls(i)}>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


CSS = """
:root {
  color-scheme: light dark;
  --bg: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series: #2a78d6; --up: #006300; --down: #c22f2f; --band: 0.16;
  --h0: #ebeae5; --h1: #b7d3f6; --h2: #6da7ec; --h3: #2a78d6; --h4: #184f95;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #9a988f;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series: #3987e5; --up: #0ca30c; --down: #e66767; --band: 0.20;
    --h0: #262624; --h1: #184f95; --h2: #256abf; --h3: #3987e5; --h4: #86b6ef;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 24px 16px 40px;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 16px; }
header, .tiles, footer, .wide { grid-column: 1 / -1; }
h1 { margin: 0; font-size: 26px; }
h2 { margin: 0 0 12px; font-size: 15px; letter-spacing: .02em; color: var(--ink-2); font-weight: 600; }
h3 { margin: 16px 0 6px; font-size: 14px; font-weight: 600; }
a { color: var(--series); text-decoration: none; }
a:hover { text-decoration: underline; }
code { font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--h0);
  padding: 1px 5px; border-radius: 4px; }
.muted { color: var(--muted); }
.small { font-size: 13px; margin: 8px 0 0; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px;
  min-width: 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tiles.mini { grid-template-columns: repeat(2, 1fr); margin-bottom: 12px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.tile .label { font-size: 13px; color: var(--ink-2); }
.tile .value { font-size: 26px; font-weight: 600; line-height: 1.3; }
.tile .note { font-size: 12px; color: var(--muted); }
.chip { white-space: nowrap; }
.chip i { display: inline-block; width: .62em; height: .62em; border-radius: 50%; margin-right: .35em;
  vertical-align: .08em; }
.progress { margin-bottom: 14px; }
.meter { height: 10px; background: var(--h0); border-radius: 5px; overflow: hidden; }
.meter span { display: block; height: 100%; background: var(--series); border-radius: 5px; }
.meter-labels { display: flex; justify-content: space-between; font-size: 13px; color: var(--ink-2);
  margin-top: 4px; font-variant-numeric: tabular-nums; }
.meter-labels strong { color: var(--ink); }
.chart { width: 100%; height: auto; display: block; }
.chart.rating { min-width: 600px; }
.chart text { font-size: 11px; fill: var(--muted); font-variant-numeric: tabular-nums; }
.chart .value { fill: var(--ink); font-weight: 600; font-size: 12px; }
.chart .band-label { fill: var(--ink-2); }
.band { opacity: var(--band); }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.target { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 4 4; }
.line { fill: none; stroke: var(--series); stroke-width: 2; stroke-linejoin: round; }
.dot { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
.hit { fill: transparent; }
.pt:hover .dot { r: 6; }
.bar { fill: var(--series); }
.pt:hover .bar { opacity: .8; }
.heat { max-width: 470px; }
.heat rect:hover { stroke: var(--ink); stroke-width: 1; }
.h0 { fill: var(--h0); background: var(--h0); } .h1 { fill: var(--h1); background: var(--h1); }
.h2 { fill: var(--h2); background: var(--h2); } .h3 { fill: var(--h3); background: var(--h3); }
.h4 { fill: var(--h4); background: var(--h4); }
.heat-legend { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 13px;
  color: var(--ink-2); margin-top: 8px; max-width: 470px; }
.heat-legend i { display: inline-block; width: 11px; height: 11px; border-radius: 2px; margin: 0 1px;
  vertical-align: -1px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th { text-align: left; font-weight: 500; color: var(--muted); font-size: 12px; border-bottom: 1px solid var(--grid);
  padding: 4px 8px; }
td { padding: 5px 8px; white-space: nowrap; border-bottom: 1px solid var(--grid); vertical-align: middle; }
tr:last-child td { border-bottom: 0; }
td.wrap { white-space: normal; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.up { color: var(--up); } .down { color: var(--down); }
.hbar { display: inline-block; width: 120px; max-width: 100%; height: 8px; background: var(--h0);
  border-radius: 4px; overflow: hidden; vertical-align: middle; }
.hbar span { display: block; height: 100%; background: var(--series); border-radius: 0 4px 4px 0; }
.focus { font-weight: 600; }
.focus::before { content: "→ "; color: var(--series); }
.done { color: var(--up); font-weight: 700; } .todo { color: var(--muted); }
.insights { margin: 0; padding-left: 18px; } .insights li { margin: 0 0 8px; }
footer { color: var(--muted); font-size: 13px; text-align: center; padding-top: 8px; }
@media (max-width: 520px) { .tile .value { font-size: 22px; } .hbar { width: 64px; } }
"""
