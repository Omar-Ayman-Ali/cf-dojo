"""Today's plan: unsolved problems around your comfort rating, plus an upsolve and a retry.

Plans are deterministic (the RNG is seeded with handle, day and reroll count) and stored in
state["plans"][day], so `dojo today`, `dojo` and `dojo bar` show the same plan all day and only
the done marks change.

Slots, with c = comfort rating:
    warmup   [c-100, c]          never below 800
    core     [c+100, c+200]      core slot i prefers focus tag i (your weakest tags)
    stretch  [c+300, c+400]      capped at target + 300
    java     [800, max(800, c-100)], preferring implementation/strings/math/sortings
    upsolve  top of the upsolve queue          retry  most urgent retry item
"""
from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from dojo.cf import metrics
from dojo.cf.model import GYM_MIN_ID, Problem, make_key, split_key
from dojo.cf.snapshot import Snapshot
from dojo.cf.upsolve import (RetryItem, UpsolveItem, mark_resolved, retry_queue,  # noqa: F401 (re-exported)
                             upsolve_queue)
from dojo.errors import DojoError
from dojo.state import State
from dojo.term import CHECK, Term, truncate, width_of
from dojo.timeutil import day_start_ts, fmt_ago, fmt_day

MIN_RATING = 800
MIN_SOLVED = 300                    # skip obscure problems
TWIN_SPAN = 3                       # Div. 1 / Div. 2 twins sit within 3 contest ids
WIDEN_STEPS = 3                     # an empty slot widens by 100 each side, up to 3 times
VARIETY_DAYS = 14                   # unsolved picks from the last 14 days aren't picked again
KEEP_DAYS = 60
JAVA_TAGS = ("implementation", "strings", "math", "sortings")
EASY_ROUNDS = frozenset({"Div. 3", "Div. 4", "Educational"})
SKIPPED = "_skipped"                # state["plans"]["_skipped"]: [{"key", "day", "slot", "reason"?}]
SLOT_LABEL = {"warmup": "warm-up", "core": "core", "stretch": "stretch", "java": "java",
              "upsolve": "upsolve", "retry": "retry"}


@dataclass
class PlanItem:
    key: str
    slot: str                       # "warmup" | "core" | "stretch" | "java" | "upsolve" | "retry"
    rating: int | None
    focus_tag: str | None = None    # tag that steered the pick (a spoiler: shown only with --tags)


@dataclass
class Plan:
    day: dt.date
    items: list[PlanItem]
    comfort: int
    rerolls: int = 0
    created_at: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "comfort": self.comfort, "rerolls": self.rerolls,
                "created_at": self.created_at,
                "items": [{"key": i.key, "slot": i.slot, "rating": i.rating, "focus_tag": i.focus_tag}
                          for i in self.items]}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Plan:
        items = [PlanItem(str(i["key"]), str(i["slot"]),
                          None if i.get("rating") is None else int(i["rating"]), i.get("focus_tag"))
                 for i in d.get("items", [])]
        return cls(dt.date.fromisoformat(d["day"]), items, int(d.get("comfort", MIN_RATING)),
                   int(d.get("rerolls", 0)), float(d.get("created_at", 0.0)))


# ---- picking ---------------------------------------------------------------------------

def plan_slots(size: int) -> list[str]:
    """1 -> core; 2 -> core, stretch; 3 -> warmup, core, stretch; 4 -> warmup, 2 core, stretch;
    5+ -> one more core, then one more stretch, alternately."""
    if size <= 0:
        return []
    if size < 4:
        return [["core"], ["core", "stretch"], ["warmup", "core", "stretch"]][size - 1]
    cores = 2 + (size - 3) // 2
    stretches = size - 1 - cores
    return ["warmup"] + ["core"] * cores + ["stretch"] * stretches


def slot_range(slot: str, comfort: int, target: int) -> tuple[int, int]:
    """Inclusive rating range of a main slot (before widening)."""
    c = comfort
    if slot == "warmup":
        return max(MIN_RATING, c - 100), max(MIN_RATING, c)
    if slot == "core":
        return c + 100, c + 200
    if slot == "stretch":
        cap = target + 300
        lo = max(c + 100, min(c + 300, cap))      # past the cap, stay at least core-hard
        return lo, max(lo, min(c + 400, cap))
    if slot == "java":
        return MIN_RATING, max(MIN_RATING, c - 100)
    raise ValueError(f"no rating range for slot {slot!r}")


def _norm_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def candidates(snap: Snapshot, exclude: Iterable[str] = ()) -> list[Problem]:
    """Problems the plan may pick, sorted by key order (contest id, index)."""
    cfg = snap.cfg
    exclude = set(exclude)
    touched = set(snap.states) | snap.all_solved
    twins: dict[str, set[int]] = {}
    for key in touched:
        p = snap.problem(key)
        if p.contest_id < GYM_MIN_ID and p.name:
            twins.setdefault(_norm_name(p.name), set()).add(p.contest_id)
    out = []
    for p in snap.problems.values():
        if (p.rating is None or p.type != "PROGRAMMING" or not cfg.min_contest_id <= p.contest_id < GYM_MIN_ID
                or "*special" in p.tags or "interactive" in p.tags
                or (p.solved_count is not None and p.solved_count < MIN_SOLVED)
                or p.key in touched or p.key in exclude):
            continue
        near = twins.get(_norm_name(p.name))
        if near and any(abs(c - p.contest_id) <= TWIN_SPAN for c in near):
            continue
        out.append(p)
    out.sort(key=lambda p: (p.contest_id, p.index))
    return out


def _weights(snap: Snapshot, pool: Sequence[Problem]) -> dict[str, float]:
    """Newer contests ×1 → ×3 (linear in contest id), Div. 3/4/Educational ×1.5, × log10(solvers)."""
    if not pool:
        return {}
    lo = min(p.contest_id for p in pool)
    hi = max(p.contest_id for p in pool)
    out = {}
    for p in pool:
        w = 1.0 + (2.0 * (p.contest_id - lo) / (hi - lo) if hi > lo else 0.0)
        c = snap.contests.get(p.contest_id)
        if c is not None and c.division in EASY_ROUNDS:
            w *= 1.5
        out[p.key] = w * math.log10(max(p.solved_count or MIN_SOLVED, 10))
    return out


def _pick(rng: random.Random, pool: Sequence[Problem], weights: dict[str, float], slot: str,
          comfort: int, target: int, taken: set[str], *, focus_tag: str | None = None,
          prefer: Sequence[str] = ()) -> PlanItem | None:
    lo, hi = slot_range(slot, comfort, target)
    for step in range(WIDEN_STEPS + 1):
        a, b = max(MIN_RATING, lo - 100 * step), hi + 100 * step
        inside = [p for p in pool if a <= p.rating <= b and p.key not in taken]
        if inside:
            break
    else:
        return None
    steer = None
    if focus_tag:
        tagged = [p for p in inside if focus_tag in p.tags]
        if tagged:
            inside, steer = tagged, focus_tag
    if prefer:
        inside = [p for p in inside if set(prefer) & set(p.tags)] or inside
    p = rng.choices(inside, weights=[weights[p.key] for p in inside])[0]
    return PlanItem(p.key, slot, p.rating, steer)


def build_plan(snap: Snapshot, *, day: dt.date, comfort: int, focus: list[str], size: int,
               java_day: bool, exclude: set[str], rerolls: int = 0,
               extras: Sequence[PlanItem] = ()) -> Plan:
    """The plan for `day`: pure and deterministic in its arguments and the snapshot.

    `extras` (upsolve / retry items) are appended as given and never picked again."""
    extras = list(extras)
    taken = {e.key for e in extras}
    pool = candidates(snap, set(exclude) | taken)
    weights = _weights(snap, pool)
    rng = random.Random(f"{snap.handle}:{day.isoformat()}:{rerolls}")
    target = snap.cfg.target_rating
    slots = plan_slots(size) + (["java"] if java_day else [])
    items: list[PlanItem] = []
    core = 0
    for slot in slots:
        tag = None
        if slot == "core":
            tag = focus[core] if core < len(focus) else None
            core += 1
        item = _pick(rng, pool, weights, slot, comfort, target, taken, focus_tag=tag,
                     prefer=JAVA_TAGS if slot == "java" else ())
        if item:
            items.append(item)
            taken.add(item.key)
    return Plan(day, items + extras, comfort, rerolls, snap.now_ts)


# ---- today's plan ----------------------------------------------------------------------

def _plans(state: State) -> dict[str, Any]:
    plans = state.get("plans", {})
    if not isinstance(plans, dict):
        plans = {}
        state.set("plans", plans)
    return plans


def _stored(plans: dict[str, Any], day: dt.date) -> Plan | None:
    raw = plans.get(day.isoformat())
    try:
        return Plan.from_json(raw) if isinstance(raw, dict) else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def skipped_keys(state: State) -> set[str]:
    out = set()
    for e in _plans(state).get(SKIPPED) or []:
        key = e.get("key") if isinstance(e, dict) else e
        if isinstance(key, str):
            out.add(key)
    return out


def recent_unsolved(snap: Snapshot, state: State, day: dt.date, days: int = VARIETY_DAYS) -> set[str]:
    """Keys recommended in the `days` plans before `day` that you still haven't solved."""
    out = set()
    for iso, raw in _plans(state).items():
        try:
            d = dt.date.fromisoformat(iso)
        except ValueError:
            continue
        if day - dt.timedelta(days=days) <= d < day and isinstance(raw, dict):
            for it in raw.get("items") or []:
                key = it.get("key") if isinstance(it, dict) else None
                if isinstance(key, str) and key not in snap.all_solved:
                    out.add(key)
    return out


def _prune(plans: dict[str, Any], today: dt.date) -> None:
    oldest = today - dt.timedelta(days=KEEP_DAYS - 1)
    for iso in list(plans):
        try:
            if dt.date.fromisoformat(iso) < oldest:
                del plans[iso]
        except ValueError:
            pass                                 # "_skipped" and anything else that isn't a day


def _focus_tags(snap: Snapshot) -> list[str]:
    try:
        from dojo.cf.analysis import focus_tags
    except ImportError:
        return []
    return list(focus_tags(snap))


def _extras(snap: Snapshot, state: State, day: dt.date, comfort: int, avoid: set[str]) -> list[PlanItem]:
    """The top upsolve problem and the most urgent retry item, skipping keys in `avoid`."""
    out = []
    up = next((u for u in upsolve_queue(snap, comfort) if u.key not in avoid), None)
    if up:
        out.append(PlanItem(up.key, "upsolve", up.rating))
    taken = avoid | {i.key for i in out}
    rt = next((r for r in retry_queue(snap, state, today=day) if r.is_due(day) and r.key not in taken), None)
    if rt:
        out.append(PlanItem(rt.key, "retry", snap.problem(rt.key).rating))
    return out


def _reroll_merge(old: Plan, new: Plan, done: set[str]) -> list[PlanItem]:
    """Old items that are done stay; each other item gets the new plan's pick for the same slot
    (k-th core for k-th core), or stays if the new plan has none. New slots go at the end."""
    fresh: dict[str, list[PlanItem]] = {}
    for it in new.items:
        fresh.setdefault(it.slot, []).append(it)
    used: dict[str, int] = {}
    items: list[PlanItem] = []
    for it in old.items:
        k = used[it.slot] = used.get(it.slot, -1) + 1
        repl = fresh.get(it.slot, [])[k:k + 1]
        items.append(it if it.key in done or not repl else repl[0])
    for slot, lst in fresh.items():
        items.extend(lst[used.get(slot, -1) + 1:])
    out: list[PlanItem] = []
    for it in items:
        if all(o.key != it.key for o in out):
            out.append(it)
    return out


def todays_plan(snap: Snapshot, state: State, *, day: dt.date | None = None, reroll: bool = False,
                focus: list[str] | None = None) -> Plan:
    """The stored plan for `day` (default today), or a new one built and stored for today.

    A stored plan is reused as is. `reroll` keeps the items already done and replaces the rest.
    Plans are never made for other days: a missing past (or future) plan is a DojoError."""
    today = snap.today
    day = day or today
    plans = _plans(state)
    stored = _stored(plans, day)
    if stored is not None and not reroll:
        return stored
    if day != today:
        if stored is None:
            raise DojoError(f"no plan for {fmt_day(day)} — plans are made on the day and kept {KEEP_DAYS} days")
        raise DojoError(f"only today's plan can be rerolled ({fmt_day(day)} isn't today)")
    snap.require("status", "problemset")
    comfort = metrics.comfort_rating(snap)
    if focus is None:
        focus = _focus_tags(snap)
    skipped = skipped_keys(state)
    exclude = recent_unsolved(snap, state, day) | skipped
    avoid = set(skipped)
    done: set[str] = set()
    if stored is not None:
        done = {i.key for i in stored.items if item_done(snap, i, day=day)}
        undone = {i.key for i in stored.items} - done
        exclude |= undone
        avoid |= undone
    extras = _extras(snap, state, day, comfort, avoid)
    # Problems from your own contests are kept for the upsolve slot.
    exclude |= {u.key for u in upsolve_queue(snap, comfort)}
    plan = build_plan(snap, day=day, comfort=comfort, focus=focus, size=snap.cfg.plan_size,
                      java_day=day.weekday() in snap.cfg.java_weekdays, exclude=exclude,
                      rerolls=stored.rerolls + 1 if stored else 0, extras=extras)
    if stored is not None:
        plan.items = _reroll_merge(stored, plan, done)
    plans[day.isoformat()] = plan.to_json()
    _prune(plans, today)
    state.touch("plans")
    return plan


def item_done(snap: Snapshot, item: PlanItem, *, day: dt.date | None = None) -> bool:
    """Solved (any AC). A "retry" item needs an AC after the plan's day began (`day`, default
    today), since a re-solve is of a problem you'd already solved."""
    if item.slot == "retry":
        since = day_start_ts(day or snap.today, snap.tz)
        st = snap.states.get(item.key)
        return bool(st and any(s.ok and s.time >= since for s in st.submissions))
    return item.key in snap.all_solved


# ---- skip ------------------------------------------------------------------------------

def _find(plan: Plan, ref: str) -> int:
    ref = ref.strip()
    if not plan.items:
        raise DojoError("today's plan is empty — nothing to skip")
    if ref.isdigit():
        if 1 <= int(ref) <= len(plan.items):
            return int(ref) - 1
        raise DojoError(f"today's plan has {len(plan.items)} problems — give a position from 1 to "
                        f"{len(plan.items)} or a problem id")
    try:
        key = make_key(*split_key(ref))
    except ValueError:
        raise DojoError(f"{ref!r} isn't a problem id (e.g. 2227B) or a position in today's plan") from None
    for i, it in enumerate(plan.items):
        if it.key.upper() == key.upper():
            return i
    have = ", ".join(it.key for it in plan.items) or "nothing"
    raise DojoError(f"{key} isn't in today's plan (it has {have})")


def _refill(snap: Snapshot, state: State, plan: Plan, old: PlanItem) -> PlanItem | None:
    """The next pick for `old`'s slot, by the same rules that filled it."""
    avoid = skipped_keys(state) | {it.key for it in plan.items}
    if old.slot == "upsolve":
        up = next((u for u in upsolve_queue(snap, plan.comfort) if u.key not in avoid), None)
        return PlanItem(up.key, "upsolve", up.rating) if up else None
    if old.slot == "retry":
        rt = next((r for r in retry_queue(snap, state, today=plan.day)
                   if r.is_due(plan.day) and r.key not in avoid), None)
        return PlanItem(rt.key, "retry", snap.problem(rt.key).rating) if rt else None
    exclude = (avoid | recent_unsolved(snap, state, plan.day)
               | {u.key for u in upsolve_queue(snap, plan.comfort)})
    pool = candidates(snap, exclude)
    rng = random.Random(f"{snap.handle}:{plan.day.isoformat()}:{plan.rerolls}:skip:{old.key}")
    return _pick(rng, pool, _weights(snap, pool), old.slot, plan.comfort, snap.cfg.target_rating, set(),
                 focus_tag=old.focus_tag, prefer=JAVA_TAGS if old.slot == "java" else ())


def skip_item(snap: Snapshot, state: State, ref: str, *,
              reason: str | None = None) -> tuple[Plan, PlanItem, PlanItem | None]:
    """Swap an unsolved item out of today's plan: (plan, skipped item, replacement or None).

    `ref` is a problem id or a 1-based position. The skipped key goes to state["plans"]["_skipped"]
    and is never planned again; the slot gets the next pick by the same rules."""
    plan = todays_plan(snap, state)
    i = _find(plan, ref)
    old = plan.items[i]
    if item_done(snap, old, day=plan.day):
        raise DojoError(f"{old.key} is already done today — nothing to skip")
    plans = _plans(state)
    log = plans.get(SKIPPED)
    if not isinstance(log, list):
        log = plans[SKIPPED] = []
    entry = {"key": old.key, "day": plan.day.isoformat(), "slot": old.slot}
    if reason:
        entry["reason"] = reason
    log.append(entry)
    new = _refill(snap, state, plan, old)
    if new:
        plan.items[i] = new
    else:
        del plan.items[i]
    plans[plan.day.isoformat()] = plan.to_json()
    state.touch("plans")
    return plan, old, new


# ---- rendering -------------------------------------------------------------------------

def problem_text(snap: Snapshot, key: str, width: int, key_width: int = 0) -> str:
    """'2254C1 Marenol (easy version)' cut to `width` cells; keys padded to `key_width` so names line up."""
    name = snap.problem(key).name
    return truncate(f"{key.ljust(key_width)} {name}".rstrip() if name else key, width)


def _is_resolve(snap: Snapshot, item: PlanItem, day: dt.date) -> bool:
    """A "retry" item for a problem you'd already solved before the plan's day."""
    st = snap.states.get(item.key)
    ac = st.first_ac if st else None
    return item.slot == "retry" and ac is not None and ac.time < day_start_ts(day, snap.tz)


def slot_label(snap: Snapshot, item: PlanItem, day: dt.date) -> str:
    return "re-solve" if _is_resolve(snap, item, day) else SLOT_LABEL.get(item.slot, item.slot)


def item_note(snap: Snapshot, item: PlanItem, day: dt.date, *, compact: bool = False) -> str:
    """The short remark after an item: Java hint, where an upsolve is from, how a retry went."""
    if item.slot == "java":
        return "in Java" if compact else f"in Java: dojo new {item.key} --java"
    st = snap.states.get(item.key)
    if compact or item.slot not in ("upsolve", "retry"):
        return ""
    if item.slot == "upsolve":
        where = snap.contest_name(split_key(item.key)[0])
        if st and any(s.in_contest or s.participant_type == "VIRTUAL" for s in st.submissions):
            return f"you tried it in {where}"
        return f"from {where}"
    if not st:
        return ""
    if _is_resolve(snap, item, day):
        return f"from scratch · {st.wrong_before_ac} failed before AC"
    n = st.wrong_total
    return f"{n} failed · last try {fmt_ago(st.last_time, snap.now_ts)}"


def _tags_line(term: Term, p: Problem, focus_tag: str | None, width: int) -> str:
    if not p.tags:
        return term.muted("no tags")
    tags = sorted(p.tags, key=lambda t: t != focus_tag)          # the steering tag first
    text = truncate(", ".join(tags), width)
    if focus_tag and (text == focus_tag or text.startswith(focus_tag + ",")):
        return term.s(focus_tag, "warn", "bold") + term.muted(text[len(focus_tag):])
    return term.muted(text)


def render_plan(plan: Plan, snap: Snapshot, term: Term, *, show_tags: bool = False,
                compact: bool = False) -> str:
    """Header and one line per item (tags on a second line with show_tags); compact=True gives
    just the item lines, for the home screen."""
    done = [item_done(snap, it, day=plan.day) for it in plan.items]
    labels = [slot_label(snap, it, plan.day) for it in plan.items]
    name_w = max(16, min(40, term.width - (32 if compact else 60)))
    key_w = max((len(it.key) for it in plan.items), default=0)
    names = [problem_text(snap, it.key, name_w, key_w) for it in plan.items]
    # indent, mark, label, name, rating and the gaps between them
    used = 2 + 1 + 2 + max(map(width_of, labels), default=0) + 2 + max(map(width_of, names), default=0) + 2 + 4 + 2
    note_w = max(12, term.width - used)
    rows = []
    for it, ok, label, name in zip(plan.items, done, labels, names):
        ref = term.link(name, snap.url(it.key))
        note = item_note(snap, it, plan.day, compact=compact)
        rows.append([term.s(CHECK, "good", "bold") if ok else term.muted("○"), term.muted(label),
                     term.s(ref, "dim") if ok else ref,
                     term.rating(it.rating) if it.rating else term.muted("—"),
                     term.muted(truncate(note, note_w)) if note else ""])
    if not rows:
        body = "  " + term.muted("nothing to suggest")
    else:
        body = term.table(rows, align="lllrl")
        if show_tags and not compact:
            lead = " " * (2 + 1 + 2 + max(map(width_of, labels)) + 2)
            lines = body.split("\n")
            body = "\n".join(line + "\n" + lead + _tags_line(term, snap.problem(it.key), it.focus_tag,
                                                              max(16, term.width - len(lead)))
                             for line, it in zip(lines, plan.items))
    if compact:
        return body
    n_done = sum(done)
    count = f"{n_done}/{len(plan.items)} done"
    finished = bool(plan.items) and n_done == len(plan.items)
    head = (term.title(fmt_day(plan.day)) + term.muted(f" · comfort {plan.comfort} · ")
            + (term.s(count, "good", "bold") if finished else term.muted(count)))
    return head + "\n\n" + body
