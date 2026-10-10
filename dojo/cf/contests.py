"""Upcoming Codeforces rounds in local time, with clashes against your class schedule.

    items = upcoming(snap, days=14)
    render_upcoming(items, term)                 # table
    render_upcoming(items, term, compact=True)   # one line: the next recommended round
    to_ics(items, snap.now)                      # calendar file with 30-minute reminders

Times come from contest.list (cached 3 h); everything shown is in cfg.tz.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from dojo.cf.model import Contest
from dojo.cf.snapshot import Snapshot
from dojo.config import ClassSlot
from dojo.term import Term, truncate, width_of
from dojo.timeutil import fmt_duration, fmt_when

RECOMMENDED = frozenset({"Div. 2", "Div. 3", "Div. 4", "Educational", "Div. 1 + Div. 2"})
LATE_BEFORE = 7                     # a round starting 00:00–06:59 local is "late"
MAX_CLASH_SECONDS = 86400           # longer rounds (practice weeks) you play when you like: no clashes
STAR, CLASH, MOON = "★", "⚠", "☾"


@dataclass
class Upcoming:
    contest: Contest
    start: dt.datetime                  # local (cfg.tz), aware
    end: dt.datetime
    division: str | None
    recommended: bool                   # Div. 2/3/4, Educational, Div. 1 + Div. 2; not Div. 1 alone
    clashes: list[ClassSlot]            # class slots the round overlaps
    late: bool                          # starts between 00:00 and 07:00 local
    running: bool = False               # already started (phase CODING)
    starts_in: float = 0.0              # seconds from the snapshot's now to the start (< 0 if running)

    @property
    def url(self) -> str:
        """The round on the contests page, where the Register link is."""
        return contests_page(self.contest.id)

    @property
    def div1_only(self) -> bool:
        return self.division == "Div. 1"

    @property
    def ends_in(self) -> float:
        return self.starts_in + self.contest.duration

    def to_json(self) -> dict:
        c = self.contest
        return {
            "id": c.id, "name": c.name, "division": self.division, "type": c.type, "phase": c.phase,
            "start": self.start.isoformat(), "end": self.end.isoformat(), "duration": c.duration,
            "starts_in": int(self.starts_in), "running": self.running, "recommended": self.recommended,
            "late": self.late, "url": self.url,
            "clashes": [{"day": s.day_name, "start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"),
                         "what": s.what} for s in self.clashes],
        }


def contests_page(contest_id: int) -> str:
    return f"https://codeforces.com/contests/{contest_id}"


def is_recommended(division: str | None) -> bool:
    return division in RECOMMENDED


def clashes(start: dt.datetime, end: dt.datetime, schedule: list[ClassSlot]) -> list[ClassSlot]:
    """Class slots overlapping [start, end): same weekday and overlapping times, checked on every
    local day the round touches (so a round crossing midnight is checked against both days)."""
    if (end - start).total_seconds() > MAX_CLASH_SECONDS:
        return []
    tz = start.tzinfo
    out: list[ClassSlot] = []
    day, last = start.date() - dt.timedelta(days=1), end.date()   # a slot crossing midnight reaches back a day
    while day <= last:
        for slot in schedule:
            if slot.day != day.weekday() or slot in out:
                continue
            s = dt.datetime.combine(day, slot.start, tz)
            e = dt.datetime.combine(day, slot.end, tz)
            if e <= s:
                e += dt.timedelta(days=1)
            if s < end and start < e:
                out.append(slot)
        day += dt.timedelta(days=1)
    return out


def upcoming(snap: Snapshot, *, days: int = 14) -> list[Upcoming]:
    """Rounds starting within `days` days, plus ones running now; sorted by start.

    Phase BEFORE and CODING only. A stale cache can still say BEFORE for a round that has
    begun or ended, so the clock decides: started → running, ended → dropped."""
    now = snap.now_ts
    horizon = now + days * 86400
    out = []
    for c in snap.contests.values():
        if c.phase not in ("BEFORE", "CODING") or c.start is None:
            continue
        end_ts = c.start + c.duration
        if end_ts <= now or c.start > horizon:
            continue
        start = dt.datetime.fromtimestamp(c.start, snap.tz)
        end = dt.datetime.fromtimestamp(end_ts, snap.tz)
        div = c.division
        out.append(Upcoming(
            contest=c, start=start, end=end, division=div, recommended=is_recommended(div),
            clashes=clashes(start, end, snap.cfg.schedule), late=start.hour < LATE_BEFORE,
            running=c.phase == "CODING" or c.start <= now, starts_in=c.start - now,
        ))
    out.sort(key=lambda u: (u.start, u.contest.id))
    return out


# ---- words ------------------------------------------------------------------------------

def when_words(u: Upcoming) -> str:
    """'today at 17:35', 'tomorrow at 17:35', 'on Sat at 18:05', 'on Sat 24 Oct at 17:35'."""
    now = u.start - dt.timedelta(seconds=u.starts_in)
    gap = (u.start.date() - now.date()).days
    hhmm = u.start.strftime("%H:%M")
    if gap == 0:
        return f"today at {hhmm}"
    if gap == 1:
        return f"tomorrow at {hhmm}"
    if gap < 7:
        return f"on {u.start.strftime('%a')} at {hhmm}"
    return f"on {u.start.strftime('%a %d %b')} at {hhmm}"


def countdown(u: Upcoming) -> str:
    return "live" if u.running else fmt_duration(u.starts_in)


def next_words(u: Upcoming) -> str:
    """The footer sentence for one round, in plain words."""
    if u.running:
        text = f"{u.contest.name} is running now, {fmt_duration(u.ends_in)} left."
    else:
        text = f"{u.contest.name}, {when_words(u)} (in {fmt_duration(u.starts_in)}, {fmt_duration(u.contest.duration)} long)."
    if u.clashes:
        text += " It overlaps " + " and ".join(s.what for s in u.clashes) + "."
    if u.late and not u.running:
        text += f" It starts at {u.start.strftime('%H:%M')} — sleep before it."
    return text


# ---- rendering --------------------------------------------------------------------------

def clash_text(slots: list[ClassSlot]) -> str:
    """'Statistics lab (CIS 208)'; with several, the course codes go: 'Statistics lab, Logic Design lab'."""
    if len(slots) == 1:
        return slots[0].what
    return ", ".join(re.sub(r"\s*\([^)]*\)\s*$", "", s.what) or s.what for s in slots)


def _markers(u: Upcoming, term: Term) -> str:
    bits = []
    if u.recommended:
        bits.append(term.s(STAR, "accent"))
    if u.running:
        bits.append(term.s(f"ends in {fmt_duration(u.ends_in)}", "good"))
    if u.late:
        bits.append(term.s(f"{MOON} late", "violet"))
    if u.clashes:
        bits.append(term.s(f"{CLASH} {clash_text(u.clashes)}", "warn"))
    return " ".join(bits)


def render_upcoming(items: list[Upcoming], term: Term, *, compact: bool = False) -> str:
    """The table of `items` (as given: filter first), or with compact=True one line for the
    next recommended round. Empty string when there's nothing to show."""
    if compact:
        u = next((u for u in items if u.recommended), None)
        if u is None:
            return ""
        name = term.link(truncate(u.contest.name, max(24, min(60, term.width - 44))), u.url)
        bits = [term.s(name, "bold")]
        if u.running:
            bits.append(term.s(f"running now, {fmt_duration(u.ends_in)} left", "good"))
        else:
            bits += [fmt_when(u.start), f"in {fmt_duration(u.starts_in)}"]
        line = "  " + term.muted(" · ").join(bits)
        if u.clashes:
            line += "  " + term.s(f"{CLASH} {clash_text(u.clashes)}", "warn")
        if u.late:
            line += "  " + term.s(f"{MOON} late", "violet")
        return line

    if not items:
        return ""
    marks = [_markers(u, term) for u in items]
    mark_w = max(width_of(m) for m in marks)
    name_w = max(30, min(70, term.width - 40 - mark_w))
    rows = []
    for u, m in zip(items, marks):
        name = truncate(u.contest.name, name_w)
        name = term.s(name, "bold") if u.recommended else term.muted(name) if u.div1_only else name
        rows.append([
            fmt_when(u.start),
            term.s(countdown(u), "good") if u.running else countdown(u),
            fmt_duration(u.contest.duration),
            term.link(name, u.url),
            m,
        ])
    return term.table(rows, header=["when", "in", "length", "round", ""], align="lrrll")


# ---- calendar ---------------------------------------------------------------------------

def _ics_text(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_time(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> list[str]:
    """RFC 5545 §3.1: lines longer than 75 octets continue on the next line after one space;
    never split inside a UTF-8 character."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not out else 74
        if size + n > limit:
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return [out[0]] + [" " + x for x in out[1:]]


def to_ics(items: list[Upcoming], now: dt.datetime) -> str:
    """An iCalendar (RFC 5545) file: one VEVENT per round in UTC, a stable UID per contest (so
    re-importing updates instead of duplicating), and a reminder 30 minutes before."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//dojo//Codeforces rounds//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Codeforces"]
    stamp = _ics_time(now)
    for u in items:
        c = u.contest
        desc = [" · ".join(x for x in (u.division, fmt_duration(c.duration),
                                       "recommended for you" if u.recommended else None) if x)]
        desc += [f"Overlaps {s.what} ({s.day_name} {s.start:%H:%M}–{s.end:%H:%M})" for s in u.clashes]
        desc.append(u.url)
        lines += [
            "BEGIN:VEVENT",
            f"UID:codeforces-contest-{c.id}@dojo",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_ics_time(u.start)}",
            f"DTEND:{_ics_time(u.end)}",
            f"SUMMARY:{_ics_text(c.name)}",
            f"DESCRIPTION:{_ics_text(chr(10).join(desc))}",
            f"URL:{u.url}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_text(c.name + ' starts in 30 minutes')}",
            "TRIGGER:-PT30M",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(part + "\r\n" for line in lines for part in _fold(line))
