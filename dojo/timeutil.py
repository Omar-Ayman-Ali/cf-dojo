"""Time helpers. Everything user-facing is in the configured timezone (Africa/Cairo)."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


def local(ts: float, tz: ZoneInfo) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, tz)


def local_date(ts: float, tz: ZoneInfo) -> dt.date:
    return dt.datetime.fromtimestamp(ts, tz).date()


def week_start(day: dt.date, start_weekday: int) -> dt.date:
    """First day of the week containing `day`; weeks begin on `start_weekday` (Mon = 0 … Sun = 6)."""
    return day - dt.timedelta(days=(day.weekday() - start_weekday) % 7)


def day_start_ts(day: dt.date, tz: ZoneInfo) -> float:
    """Epoch seconds of local midnight starting `day`."""
    return dt.datetime.combine(day, dt.time(), tz).timestamp()


def fmt_duration(seconds: float) -> str:
    """90 -> '1m 30s'; 3600*26 -> '1d 2h'. Two largest units."""
    s = int(abs(seconds))
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if s >= size or (unit == "s" and not parts):
            parts.append(f"{s // size}{unit}")
            s %= size
        if len(parts) == 2:
            break
    return " ".join(parts)


def fmt_ago(ts: float, now: float) -> str:
    d = now - ts
    if d < 60:
        return "just now"
    if d < 86400 * 2:
        return fmt_duration(d).split()[0] + " ago"
    return f"{int(d // 86400)} days ago"


def fmt_when(when: dt.datetime) -> str:
    """'Wed 07 Oct 17:35'."""
    return when.strftime("%a %d %b %H:%M")


def fmt_day(day: dt.date) -> str:
    """'Wed 07 Oct'."""
    return day.strftime("%a %d %b")
