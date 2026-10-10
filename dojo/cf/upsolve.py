"""Queues of problems to come back to.

upsolve  unsolved problems from contests you took part in: rated rounds, rounds where you
         submitted during the contest, and virtual participations.
retry    problems you failed and never solved, plus hard-won solves (2+ failed attempts before
         the AC) due for a from-scratch re-solve: spaced repetition for the bugs you made.

Re-solve schedule, kept in state["resolve"][key] = {"stage": 0|1|2|3, "due": iso|None, "done": [iso…]}:
re-solve n is due `RESOLVE_INTERVALS[n]` days after the first AC. Done late, the next one is
pushed back so the gap between re-solves never shrinks (`_complete`). Stage 3 means retired.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from dojo.cf.model import GYM_MIN_ID, Submission
from dojo.cf.snapshot import Snapshot
from dojo.errors import DojoError
from dojo.state import State
from dojo.timeutil import fmt_day

RATING_SLACK = 500                  # upsolve problems rated up to comfort + 500
INDEX_SLACK = 2                     # unrated problems: up to two letters past your best solve there
RESOLVE_INTERVALS = (3, 10, 30)     # days after the first AC
RESOLVE_WINDOW = 120                # only solves from the last 120 days get a new schedule
RESOLVE_MIN_WRONG = 2


# ---- upsolve ---------------------------------------------------------------------------

@dataclass
class UpsolveItem:
    key: str
    contest_id: int
    contest_name: str
    index: str
    rating: int | None
    attempted: bool                 # you submitted it during the contest (or your virtual run)
    contest_time: int               # when you took part: contest start; virtual: your first submission


def index_order(index: str) -> tuple[str, int, str]:
    """Sort key for problem indexes: A < B < C1 < C2 < D … < Z < AA."""
    m = re.match(r"([A-Za-z]+)(\d*)(.*)$", index)
    if not m:
        return ("~", 0, index)
    letters = m.group(1).upper()
    return (f"{len(letters)}{letters}", int(m.group(2) or 0), m.group(3))


def _letter(index: str) -> int:
    """Position of the index's letter: A = 0, B = 1, C1 = C2 = 2."""
    return ord(index[:1].upper() or "A") - ord("A")


def _in_run(s: Submission) -> bool:
    return s.in_contest or s.participant_type == "VIRTUAL"


def contests_taken(snap: Snapshot) -> dict[int, tuple[int, str]]:
    """Public contests you took part in -> (when, how), how ∈ 'rated', 'live', 'virtual'."""
    live: dict[int, int] = {}
    virtual: dict[int, int] = {}
    for s in snap.submissions:                       # ascending, so setdefault keeps the first
        if s.contest_id >= GYM_MIN_ID:
            continue
        if s.in_contest:
            live.setdefault(s.contest_id, s.time)
        elif s.participant_type == "VIRTUAL":
            virtual.setdefault(s.contest_id, s.time)
    rated = {r.contest_id: r.time for r in snap.rating_history}
    out: dict[int, tuple[int, str]] = {}
    for cid in set(rated) | set(live):
        c = snap.contests.get(cid)
        when = c.start if c and c.start else live.get(cid, rated.get(cid, 0))
        out[cid] = (int(when), "rated" if cid in rated else "live")
    for cid, when in virtual.items():
        out.setdefault(cid, (when, "virtual"))
    return out


def upsolve_queue(snap: Snapshot, comfort: int, *, uncapped: bool = False) -> list[UpsolveItem]:
    """Unsolved problems from your contests, newest contest first, then by index.

    Kept: rated problems up to comfort + 500; unrated ones (fresh rounds have no ratings yet) up
    to two letters past the furthest problem you solved in that contest. `uncapped` keeps all.
    """
    taken = contests_taken(snap)
    by_contest: dict[int, list] = {}
    for p in snap.problems.values():
        if p.contest_id in taken:
            by_contest.setdefault(p.contest_id, []).append(p)
    items: list[UpsolveItem] = []
    for cid, probs in by_contest.items():
        best = max((_letter(p.index) for p in probs if p.key in snap.all_solved), default=-1)
        name = snap.contest_name(cid)
        when = taken[cid][0]
        for p in probs:
            if p.key in snap.all_solved:
                continue
            if not uncapped:
                if p.rating is not None and p.rating > comfort + RATING_SLACK:
                    continue
                if p.rating is None and _letter(p.index) > best + INDEX_SLACK:
                    continue
            st = snap.states.get(p.key)
            attempted = bool(st and any(_in_run(s) for s in st.submissions))
            items.append(UpsolveItem(p.key, cid, name, p.index, p.rating, attempted, when))
    items.sort(key=lambda u: (-u.contest_time, -u.contest_id, index_order(u.index)))
    return items


# ---- retry -----------------------------------------------------------------------------

@dataclass
class RetryItem:
    key: str
    kind: str                       # "unsolved" (failed, never AC) | "resolve" (hard-won, re-solve it)
    wrong: int                      # failed attempts (before the first AC, for resolve)
    last_time: int                  # last submission time
    due: dt.date | None             # resolve only
    stage: int                      # resolve only: 0, 1, 2 -> re-solve 1, 2, 3 of 3

    def is_due(self, today: dt.date) -> bool:
        """Belongs in today's work: any unsolved problem, or a re-solve whose day has come."""
        return self.kind == "unsolved" or (self.due is not None and self.due <= today)


def _date(text: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _valid(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    stage, due, done = entry.get("stage"), entry.get("due"), entry.get("done")
    if not isinstance(stage, int) or isinstance(stage, bool) or not 0 <= stage <= len(RESOLVE_INTERVALS):
        return False
    if not isinstance(done, list) or not all(_date(d) for d in done):
        return False
    return due is None if stage == len(RESOLVE_INTERVALS) else _date(due) is not None


def _new_entry(first: dt.date) -> dict[str, Any]:
    return {"stage": 0, "due": (first + dt.timedelta(days=RESOLVE_INTERVALS[0])).isoformat(), "done": []}


def _complete(entry: dict[str, Any], first: dt.date, day: dt.date) -> None:
    """Record the current re-solve as done on `day` and schedule the next one.

    The next is due at first AC + its interval, but never sooner than the scheduled gap after
    this one (7 days, then 20), so a late re-solve doesn't make the next one due at once."""
    entry["done"].append(day.isoformat())
    stage = entry["stage"] = entry["stage"] + 1
    if stage >= len(RESOLVE_INTERVALS):
        entry["due"] = None
        return
    gap = RESOLVE_INTERVALS[stage] - RESOLVE_INTERVALS[stage - 1]
    due = max(first + dt.timedelta(days=RESOLVE_INTERVALS[stage]), day + dt.timedelta(days=gap))
    entry["due"] = due.isoformat()


def _schedule(state: State) -> dict[str, Any]:
    sched = state.get("resolve", {})
    if not isinstance(sched, dict):
        sched = {}
        state.set("resolve", sched)
    return sched


def retry_queue(snap: Snapshot, state: State, *, today: dt.date | None = None) -> list[RetryItem]:
    """Due re-solves (most overdue first), then unsolved problems (most recent first), then
    re-solves that aren't due yet (callers filter those with RetryItem.is_due).

    Syncs state["resolve"]: schedules new hard-won solves from the last 120 days, completes a
    stage when the snapshot has an AC on/after its due date, retires after the third re-solve,
    and forgets schedules you never started once their solve is older than 120 days."""
    today = today or snap.today
    sched = _schedule(state)
    horizon = today - dt.timedelta(days=RESOLVE_WINDOW)
    changed = False
    due_now: list[RetryItem] = []
    later: list[RetryItem] = []
    for key, st in snap.states.items():
        first_ac = st.first_ac
        if first_ac is None or st.wrong_before_ac < RESOLVE_MIN_WRONG:
            continue
        first = snap.local_date(first_ac.time)
        recent = first >= horizon
        raw = sched.get(key)
        entry = raw if _valid(raw) else None
        if entry is None:
            if not recent:
                if raw is not None:
                    del sched[key]
                    changed = True
                continue
            entry = sched[key] = _new_entry(first)
            changed = True
        for s in st.submissions:
            if (s.ok and s.time > first_ac.time and entry["due"] is not None
                    and snap.local_date(s.time) >= dt.date.fromisoformat(entry["due"])):
                _complete(entry, first, snap.local_date(s.time))
                changed = True
        if not recent and (entry["due"] is None or not entry["done"]):
            del sched[key]                       # retired, or never started: nothing left to track
            changed = True
            continue
        if entry["due"] is None:
            continue                             # retired; kept so it isn't scheduled again
        due = dt.date.fromisoformat(entry["due"])
        item = RetryItem(key, "resolve", st.wrong_before_ac, st.last_time, due, entry["stage"])
        (due_now if due <= today else later).append(item)
    if changed:
        state.touch("resolve")

    unsolved = [RetryItem(k, "unsolved", snap.states[k].wrong_total, snap.states[k].last_time, None, 0)
                for k in snap.attempted_unsolved]
    due_now.sort(key=lambda r: (r.due, -r.wrong, r.key))
    unsolved.sort(key=lambda r: (-r.last_time, r.key))
    later.sort(key=lambda r: (r.due, r.key))
    return due_now + unsolved + later


def mark_resolved(snap: Snapshot, state: State, key: str, *,
                  today: dt.date | None = None) -> RetryItem | None:
    """Record today's from-scratch re-solve of `key`. Returns the next scheduled re-solve, or
    None when that was the last one (retired). Raises DojoError when there's nothing to record."""
    today = today or snap.today
    queue = retry_queue(snap, state, today=today)
    item = next((r for r in queue if r.key == key), None)
    sched = _schedule(state)
    if item is None:
        entry = sched.get(key)
        if _valid(entry) and entry["due"] is None:
            raise DojoError(f"{key}: all {len(RESOLVE_INTERVALS)} re-solves are already done")
        if key not in snap.states:
            raise DojoError(f"{key}: no submissions of yours for it — check the id")
        raise DojoError(f"{key} isn't on the re-solve schedule (only solves from the last {RESOLVE_WINDOW} days "
                        f"that took {RESOLVE_MIN_WRONG}+ failed attempts are)")
    if item.kind == "unsolved":
        raise DojoError(f"{key} isn't solved yet — it leaves the list by itself when you get AC")
    entry = sched[key]
    if entry["done"] and entry["done"][-1] == today.isoformat():
        raise DojoError(f"{key}: today's re-solve is already recorded — the next one is due "
                        f"{fmt_day(dt.date.fromisoformat(entry['due']))}")
    st = snap.states[key]
    _complete(entry, snap.local_date(st.first_ac.time), today)
    state.touch("resolve")
    if entry["due"] is None:
        return None
    return RetryItem(key, "resolve", st.wrong_before_ac, st.last_time, dt.date.fromisoformat(entry["due"]),
                     entry["stage"])
