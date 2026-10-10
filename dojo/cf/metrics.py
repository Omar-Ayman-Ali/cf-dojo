"""Shared training metrics. One definition each, used by status, today, report and bar."""
from __future__ import annotations

import datetime as dt
import math

from dojo.cf.snapshot import Snapshot
from dojo.timeutil import day_start_ts, week_start

RECENT_DAYS = 90
MIN_RATING = 800


def floor100(x: float) -> int:
    return int(math.floor(x / 100.0) * 100)


def solved_ratings(snap: Snapshot, since_ts: float | None = None) -> list[int]:
    """Rating of each solved problem (first AC at or after since_ts), where the rating is known."""
    out = []
    for key, st in snap.states.items():
        ac = st.first_ac
        if not ac or (since_ts is not None and ac.time < since_ts):
            continue
        r = snap.problems[key].rating if key in snap.problems else ac.rating
        if r:
            out.append(int(r))
    return out


def comfort_rating(snap: Snapshot) -> int:
    """The difficulty you reliably solve: the 75th percentile (nearest rank) of ratings you've
    solved in the last 90 days — all time if fewer than 5 — floored to 100, never below 800 and
    never below your contest rating minus 100."""
    recent = solved_ratings(snap, snap.now_ts - RECENT_DAYS * 86400)
    pool = sorted(recent if len(recent) >= 5 else solved_ratings(snap))
    p75 = pool[max(0, math.ceil(0.75 * len(pool)) - 1)] if pool else MIN_RATING
    base = floor100(p75)
    if snap.rating is not None:
        base = max(base, floor100(snap.rating - 100))
    return max(MIN_RATING, base)


def current_streak(days: list[dt.date], today: dt.date) -> int:
    """Consecutive active days ending today — or yesterday, since today isn't over yet."""
    have = set(days)
    d = today if today in have else today - dt.timedelta(days=1)
    n = 0
    while d in have:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def best_streak(days: list[dt.date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(set(days)):
        run = run + 1 if prev is not None and d - prev == dt.timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def week_window(snap: Snapshot, day: dt.date | None = None) -> tuple[dt.date, float, float]:
    """(first day, start ts, end ts) of the training week containing `day` (default today)."""
    start = week_start(day or snap.today, snap.cfg.week_start_day)
    return start, day_start_ts(start, snap.tz), day_start_ts(start + dt.timedelta(days=7), snap.tz)


def solved_this_week(snap: Snapshot) -> list[str]:
    _, a, b = week_window(snap)
    return snap.solved_between(a, b)


def daily_counts(snap: Snapshot, days: int = 28) -> list[tuple[dt.date, int]]:
    """Problems first solved per local day, oldest first, ending today."""
    today = snap.today
    counts = {today - dt.timedelta(days=i): 0 for i in range(days)}
    for t in snap.ac_times:
        d = snap.local_date(t)
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


def weekly_counts(snap: Snapshot, weeks: int = 12) -> list[tuple[dt.date, int]]:
    """Problems first solved per training week, oldest first, ending with the current week."""
    this_week = week_start(snap.today, snap.cfg.week_start_day)
    starts = [this_week - dt.timedelta(weeks=i) for i in range(weeks)]
    counts = dict.fromkeys(starts, 0)
    for t in snap.ac_times:
        w = week_start(snap.local_date(t), snap.cfg.week_start_day)
        if w in counts:
            counts[w] += 1
    return sorted(counts.items())
