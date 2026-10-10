"""Analytics: where you stand (overview + insights) and which tags to practise (tag profile).

    ov = overview(snap)                  # the numbers behind `dojo status`, the home screen, the report
    term.out(render_status(ov, term))
    focus_tags(snap)                     # ['constructive algorithms', 'greedy', 'math'] — steers `dojo today`

Everything here is a pure function of the Snapshot (the clock is snap.now_ts) and renders to
strings, so the home screen and the HTML report can call it freely.
"""
from __future__ import annotations

import datetime as dt
import re
import textwrap
from collections import Counter
from dataclasses import dataclass, field

from dojo.cf import metrics
from dojo.cf.model import GYM_MIN_ID, VERDICT_SHORT, RatingChange
from dojo.cf.snapshot import Snapshot
from dojo.errors import DojoError
from dojo.term import ARROW, Term, next_rank, rank_of, truncate, width_of
from dojo.timeutil import day_start_ts, fmt_day, fmt_when

SPECIAL = "*special"
SHOW_INSIGHTS = 3                # status shows the top 3
WINDOW = 21                      # volume drop: first ACs in the last 21 days vs the 21 before
IDLE_DAYS = 3                    # "no AC for n days" from this many days
FOCUS_MIN_IMPORTANCE = 0.05      # focus_tags only steers to tags at least this common
SHOW_MIN_IMPORTANCE = 0.03       # `dojo weak` and the report hide rarer tags unless asked
FAIL_PRIOR = 4                   # pseudo-attempts pulling a tag's fail rate toward your average
HIST_BUCKETS = list(range(800, 1700, 100))      # 800 … 1600, the last one meaning 1600+
SAFE_COMPILER = "C++23 (GCC 14-64, msys2)"


# ---- overview -----------------------------------------------------------------------------

@dataclass
class Insight:
    priority: int          # higher = more important; status shows the top 3
    text: str              # one sentence, specific, with numbers, ends with an action when there is one


@dataclass
class Overview:
    handle: str
    rating: int | None
    max_rating: int | None
    rank: str                                       # 'newbie', 'pupil', … or 'unrated'
    target: int
    to_target: int | None                           # target - rating (None if unrated)
    contests: int
    rating_history: list[RatingChange]
    solved_total: int                               # len(snap.all_solved)
    solved_problemset: int                          # contest_id < GYM_MIN_ID
    solved_groups: int                              # contest_id >= GYM_MIN_ID
    week_start: dt.date
    week_solved: int
    week_goal: int
    streak: int
    best_streak: int
    active_today: bool
    last_ac: dt.datetime | None                     # latest accepted submission, local time
    daily: list[tuple[dt.date, int]]                # metrics.daily_counts(snap, 28)
    weekly: list[tuple[dt.date, int]]               # metrics.weekly_counts(snap, 12)
    verdicts: Counter                               # verdict -> count over all submissions
    wa_per_ac: float                                # WRONG_ANSWER count / OK count (0 if no OK)
    first_try_rate: float                           # solved problems with wrong_before_ac == 0 / solved
    comfort: int                                    # metrics.comfort_rating
    by_rating: dict[int, int]                       # solved count per rating (rated problems only)
    authenticated: bool
    insights: list[Insight]                         # sorted by priority, descending
    as_of: dt.datetime | None = None                # snap.now (local): "10 days ago", "4 days left"


def overview(snap: Snapshot) -> Overview:
    """Everything `dojo status` shows, computed from the snapshot."""
    cfg = snap.cfg
    rating = snap.rating
    solved_states = [st for st in snap.states.values() if st.solved]
    verdicts = Counter(s.verdict for s in snap.submissions if s.verdict)
    ok = verdicts["OK"]
    last_ok = max((s.time for s in snap.submissions if s.ok), default=None)
    groups = sum(1 for k in snap.all_solved if _contest_id(k) >= GYM_MIN_ID)
    by_rating = Counter(r for r in (problem_rating(snap, k) for k in snap.all_solved) if r)
    ov = Overview(
        handle=str((snap.user or {}).get("handle") or snap.handle),
        rating=rating,
        max_rating=snap.max_rating,
        rank="unrated" if rating is None else (snap.rank or rank_of(rating)[0]),
        target=cfg.target_rating,
        to_target=None if rating is None else cfg.target_rating - rating,
        contests=len(snap.rating_history),
        rating_history=list(snap.rating_history),
        solved_total=len(snap.all_solved),
        solved_problemset=len(snap.all_solved) - groups,
        solved_groups=groups,
        week_start=metrics.week_window(snap)[0],
        week_solved=len(metrics.solved_this_week(snap)),
        week_goal=cfg.weekly_goal,
        streak=metrics.current_streak(snap.ac_days, snap.today),
        best_streak=metrics.best_streak(snap.ac_days),
        active_today=snap.today in set(snap.ac_days),
        last_ac=None if last_ok is None else dt.datetime.fromtimestamp(last_ok, snap.tz),
        daily=metrics.daily_counts(snap, 28),
        weekly=metrics.weekly_counts(snap, 12),
        verdicts=verdicts,
        wa_per_ac=verdicts["WRONG_ANSWER"] / ok if ok else 0.0,
        first_try_rate=(sum(st.wrong_before_ac == 0 for st in solved_states) / len(solved_states)
                        if solved_states else 0.0),
        comfort=metrics.comfort_rating(snap),
        by_rating=dict(sorted(by_rating.items())),
        authenticated=snap.authenticated,
        insights=[],
        as_of=snap.now,
    )
    found = [rule(snap, ov) for rule in _RULES]
    ov.insights = sorted((i for i in found if i), key=lambda i: -i.priority)
    return ov


def target_name(target: int) -> str:
    """'Pupil' when the target is where a rank starts (1200), else the number ('1300')."""
    name = rank_of(target)[0]
    return name.title() if rank_of(target - 1)[0] != name else str(target)


# ---- insights: each rule returns an Insight only when it's true --------------------------------

def _access(snap: Snapshot, ov: Overview) -> Insight | None:
    if "status" not in snap.loaded or snap.authenticated:
        return None
    if ov.solved_groups:
        return Insight(95, f"Only public submissions are visible, so verdicts and streaks miss your "
                           f"{_plural(ov.solved_groups, 'group solve')} — add CF_API_KEY/CF_API_SECRET to include group training.")
    return Insight(35, "Only public submissions are visible — add CF_API_KEY/CF_API_SECRET to include group training.")


def _activity(snap: Snapshot, ov: Overview) -> Insight | None:
    """Inactivity and volume drop, merged when both hold (they're the same problem)."""
    if "status" not in snap.loaded:
        return None
    if ov.last_ac is None:
        n = sum(ov.verdicts.values())
        if n:
            return Insight(90, f"No accepted solution yet in {n} submissions — start with the warm-up "
                               f"problem in `dojo today`.")
        return Insight(90, "No submissions yet — `dojo today` picks your first problems.")
    today = snap.today
    idle = (today - ov.last_ac.date()).days
    recent, before = _volume(snap)
    dropped = before >= 6 and 2 * recent <= before
    since = f"since {fmt_day(ov.last_ac.date())} ({idle} days)"
    if idle >= IDLE_DAYS and dropped and recent:
        return Insight(90, f"No AC {since}; {recent} solves in the last 3 weeks vs {before} in the 3 "
                           f"before — restart small with `dojo today`.")
    if idle >= IDLE_DAYS:
        return Insight(90, f"No accepted problem {since} — one easy problem today restarts your "
                           f"streak: `dojo today`.")
    if dropped:
        return Insight(85, f"{recent} solves in the last 3 weeks, down from {before} in the 3 weeks "
                           f"before — a small daily plan beats a big weekly one: `dojo today`.")
    return None


def _volume(snap: Snapshot) -> tuple[int, int]:
    """First ACs in the last 21 local days (today included) and in the 21 days before."""
    today = snap.today
    start = day_start_ts(today - dt.timedelta(days=WINDOW - 1), snap.tz)
    prev = day_start_ts(today - dt.timedelta(days=2 * WINDOW - 1), snap.tz)
    recent = sum(1 for t in snap.ac_times if t >= start)
    before = sum(1 for t in snap.ac_times if prev <= t < start)
    return recent, before


def _streak(snap: Snapshot, ov: Overview) -> Insight | None:
    if ov.streak >= 2 and not ov.active_today:
        return Insight(88, f"{ov.streak}-day streak — solve one today to keep it.")
    return None


def _debugging(snap: Snapshot, ov: Overview) -> Insight | None:
    ok, wa = ov.verdicts["OK"], ov.verdicts["WRONG_ANSWER"]
    solved = [st for st in snap.states.values() if st.solved]
    hard = sum(st.wrong_before_ac >= 3 for st in solved)
    tail = " — before resubmitting, run `dojo stress`."
    if ok >= 10 and ov.wa_per_ac >= 0.5:
        text = f"{wa} wrong answers vs {ok} accepted ({ov.wa_per_ac:.2f} per AC)"
        if hard:
            text += f"; {hard} of your {len(solved)} solves needed 3+ failed attempts"
        return Insight(70, text + tail)
    if hard >= 3 and hard >= 0.1 * len(solved):
        return Insight(70, f"{hard} of your {len(solved)} solves needed 3+ failed attempts" + tail)
    return None


def _upsolve(snap: Snapshot, ov: Overview) -> Insight | None:
    if "problemset" not in snap.loaded:
        return None
    try:
        from dojo.cf.upsolve import upsolve_queue
        queue = upsolve_queue(snap, ov.comfort)
    except (ImportError, DojoError):
        return None
    if not queue:
        return None
    # The easiest one, preferring a problem you already tried; min() keeps queue order on ties.
    pick = min(queue, key=lambda u: (u.rating if u.rating is not None else 10**9, not u.attempted))
    name = pick.contest_name or f"contest {pick.contest_id}"
    what = pick.key + (f" ({pick.rating})" if pick.rating else "")
    where = f", which you tried in {name}," if pick.attempted else f" from {name}"
    more = len(queue) - 1
    return Insight(60, f"{what}{where} is still unsolved" + (f", plus {more} more from your contests" if more else "")
                   + " — `dojo upsolve`.")


def _week_pace(snap: Snapshot, ov: Overview) -> Insight | None:
    """Only when the goal is within reach: started this week, at most 2 a day still needed."""
    goal, done = ov.week_goal, ov.week_solved
    last_day = ov.week_start + dt.timedelta(days=6)
    days_left = (last_day - snap.today).days + 1
    left = goal - done
    if goal <= 0 or done == 0 or left <= 0 or left > 2 * days_left:
        return None
    return Insight(55, f"{done}/{goal} this week — {left} more by {last_day:%a} reaches your goal.")


def _target(snap: Snapshot, ov: Overview) -> Insight | None:
    if ov.rating is None:
        if not {"rating", "user"} & snap.loaded:
            return None
        return Insight(50, "No rated rounds yet — your first Div. 3 or Div. 4 round sets your rating: "
                           "`dojo contests`.")
    if ov.to_target is None or ov.to_target <= 0:
        return None
    text = f"{ov.to_target} rating to {target_name(ov.target)}."
    rounds = ov.rating_history[-3:]
    hint = "solving A–C quickly usually gives a 1200+ performance" if ov.target <= 1200 else ""
    if rounds and "status" in snap.loaded:
        counts = [len({s.key for s in snap.submissions if s.ok and s.in_contest and s.contest_id == r.contest_id})
                  for r in rounds]
        text += " " + _rounds_phrase(counts, len(ov.rating_history))
        text += f"; in a Div. 3, {hint}." if hint else "."
    elif hint:
        text += f" Div. 3 rounds: {hint}."
    return Insight(50, text)


def _rounds_phrase(counts: list[int], total: int) -> str:
    """'You solved 1 problem in each of your 3 rated rounds' / '… 1, 2 and 4 problems in your last 3 …'."""
    k = len(counts)
    which = f"your {k} rated rounds" if k == total else f"your last {k} rated rounds"
    if k == 1:
        c = counts[0]
        return f"You solved {c} problem{'' if c == 1 else 's'} in your " + ("rated round" if total == 1 else "last rated round")
    if len(set(counts)) == 1:
        c = counts[0]
        return f"You solved {c} problem{'' if c == 1 else 's'} in each of {which}"
    return f"You solved {', '.join(map(str, counts[:-1]))} and {counts[-1]} problems in {which}"


def _last_round(snap: Snapshot, ov: Overview) -> Insight | None:
    if not ov.rating_history:
        return None
    last = ov.rating_history[-1]
    c = snap.contests.get(last.contest_id)
    when = c.start if c and c.start else last.time
    days = (snap.today - snap.local_date(when)).days
    if days < 30:
        return None
    return Insight(45, f"Your last rated round was {days} days ago ({last.contest_name}) — "
                       f"`dojo contests` lists the next ones.")


_GCC = re.compile(r"GCC (\d+)(?:-(\d+))?")                 # 'C++17 (GCC 7-32)', 'C++23 (GCC 14-64, msys2)'
_GNU = re.compile(r"G\+\+\d*\s+(\d+)\.\d+")                # 'GNU G++17 7.3.0', 'GNU G++17 9.2.0 (64 bit, msys 2)'


def compiler_issue(language: str) -> str | None:
    """Why a C++ compiler choice is risky ('a 32-bit compiler', 'an old compiler (GCC 9)'), or None."""
    if "++" not in language:
        return None
    m = _GCC.search(language)
    if m:
        version, bits = int(m.group(1)), m.group(2) or "64"
    else:
        m = _GNU.search(language)
        if not m:
            return None
        version, bits = int(m.group(1)), "64" if "64" in language else "32"
    if bits == "32":
        return "a 32-bit compiler"
    if version <= 9:
        return f"an old compiler (GCC {version})"
    return None


def _compiler(snap: Snapshot, ov: Overview) -> Insight | None:
    recent = snap.submissions[-20:]
    old = [(s, why) for s in recent if (why := compiler_issue(s.language))]
    if not old:
        return None
    s, why = old[-1]
    return Insight(40, f"{len(old)} of your last {len(recent)} submissions used {s.language}, {why} — "
                       f"pick {SAFE_COMPILER}.")


_RULES = (_access, _activity, _streak, _debugging, _upsolve, _week_pace, _target, _last_round, _compiler)


# ---- rendering ----------------------------------------------------------------------------------

def render_status(ov: Overview, term: Term, *, compact: bool = False) -> str:
    """The `dojo status` screen; compact=True: at most 3 lines for the home screen
    (rating → target bar, week x/goal, streak, top insight)."""
    return _compact(ov, term) if compact else _full(ov, term)


def _today(ov: Overview) -> dt.date:
    return ov.as_of.date() if ov.as_of else ov.daily[-1][0] if ov.daily else dt.date.today()


def _ago(day: dt.date, today: dt.date) -> str:
    n = (today - day).days
    return "today" if n == 0 else "yesterday" if n == 1 else f"{n} days ago"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _progress(ov: Overview, term: Term, bar_width: int) -> str:
    """'747 ███████████████░░░░░░░░░ 1200 · 453 to Pupil'."""
    name = target_name(ov.target)
    if ov.rating is None:
        goal = f"target {ov.target}" + ("" if name.isdigit() else f" ({name})")
        return term.muted(f"unrated · {goal}")
    frac = ov.rating / ov.target if ov.target > 0 else 1.0
    out = f"{term.rating(ov.rating)} {term.bar(frac, bar_width)} {term.rating(ov.target)} {term.muted('·')} "
    if ov.to_target is not None and ov.to_target > 0:
        return out + term.s(f"{ov.to_target} to {name}", "bold")
    nxt = next_rank(ov.rating)
    return out + term.s("target reached", "good") + (
        term.muted(f" · {nxt[0] - ov.rating} to {nxt[1].title()}") if nxt else "")


def _wrap(text: str, width: int) -> list[str]:
    """Wrap plain text without splitting a `command` across lines."""
    guarded = re.sub(r"`[^`]*`", lambda m: m.group(0).replace(" ", "\0"), text)
    lines = textwrap.wrap(guarded, max(20, width), break_on_hyphens=False) or [""]
    return [line.replace("\0", " ") for line in lines]


def _code(line: str, term: Term) -> str:
    """`dojo today` -> bold when colour is on; plain output keeps the backticks."""
    if not term.color:
        return line
    return re.sub(r"`([^`]*)`", lambda m: term.s(m.group(1), "bold"), line)


def _insight_lines(insight: Insight, term: Term, width: int, max_lines: int | None = None) -> list[str]:
    lines = _wrap(insight.text, width - 4)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = truncate(lines[-1] + " …", width - 4)
    return [("  " + term.s(ARROW, "accent") + " " if i == 0 else "    ") + _code(line, term)
            for i, line in enumerate(lines)]


def _compact(ov: Overview, term: Term) -> str:
    width = max(40, term.width)
    a = "  " + term.rating(ov.rating, ov.handle) + " " + _progress(ov, term, 16)
    b = f"week {ov.week_solved}/{ov.week_goal} {term.muted('·')} streak {ov.streak}"
    if ov.best_streak > ov.streak:
        b += term.muted(f" (best {ov.best_streak})")
    sep = term.muted(" · ")
    lines = [a + sep + b] if width_of(a + sep + b) <= width else [a, "  " + b]
    if ov.insights:
        lines += _insight_lines(ov.insights[0], term, width, max_lines=3 - len(lines))
    return "\n".join(lines)


def _full(ov: Overview, term: Term) -> str:
    width = max(40, term.width)
    today = _today(ov)
    tz = ov.as_of.tzinfo if ov.as_of else None
    out: list[str] = []

    rank = "unrated" if ov.rating is None else ov.rank.title()
    head = term.rating(ov.rating, ov.handle) + term.muted(f" · {rank}")
    if ov.max_rating is not None and ov.rating is not None and ov.max_rating > ov.rating:
        head += term.muted(" · max ") + term.rating(ov.max_rating)
    out += [head, "  " + _progress(ov, term, 24 if width >= 70 else 12)]

    # rated rounds
    hist = ov.rating_history
    if hist:
        out.append(term.section("rated rounds") + term.muted(f"  {len(hist)} · ")
                   + term.s(term.spark([r.new for r in hist]), "accent"))
        rows = []
        for r in hist[-5:]:
            when = dt.datetime.fromtimestamp(r.time, tz).strftime("%d %b %Y")
            delta = term.s(f"{r.delta:+d}", "good" if r.delta >= 0 else "bad")
            rows.append([term.muted(when), r.contest_name, term.muted(f"#{r.rank}"), delta, term.rating(r.new)])
        others = [max(width_of(row[i]) for row in rows) for i in (0, 2, 3, 4)]
        room = width - 2 - sum(others) - 2 * 4
        for row in rows:
            row[1] = truncate(row[1], max(12, room))
        out.append(term.table(rows, align="llrrr"))
        if len(hist) > 5:
            out.append("  " + term.muted(f"… {_plural(len(hist) - 5, 'earlier round')}"))
    else:
        out += [term.section("rated rounds"),
                "  " + term.muted("none yet — a Div. 3 or Div. 4 round sets your rating (`dojo contests`)")]

    # solved
    out.append(term.section("solved") + "  " + term.s(ov.solved_total, "bold")
               + term.muted(f" · {ov.solved_problemset} from the problemset · {ov.solved_groups} from groups"))
    rated = sum(ov.by_rating.values())
    hist_text = _histogram(ov.by_rating, term, width - 13)
    out.append(_kv([
        ("by rating", hist_text + term.muted(f"   {rated} with a rating")),
        ("comfort", term.rating(ov.comfort) + term.muted(" — the rating you solve reliably (last 90 days)")),
    ], term))

    # activity
    week_end = ov.week_start + dt.timedelta(days=6)
    days_left = (week_end - today).days + 1
    week = (f"{ov.week_solved}/{ov.week_goal} " + term.bar(ov.week_solved / ov.week_goal if ov.week_goal else 1.0,
                                                           20 if width >= 70 else 10)
            + term.muted(f"  since {fmt_day(ov.week_start)}" + (f" · {_plural(days_left, 'day')} left"
                                                                 if 0 < days_left <= 7 else "")))
    streak = _plural(ov.streak, "day") + term.muted(f" · best {ov.best_streak}")
    if ov.active_today:
        streak += term.muted(" · solved today")
    if ov.last_ac:
        streak += term.muted(f" · last AC {fmt_when(ov.last_ac)} ({_ago(ov.last_ac.date(), today)})")
    else:
        streak += term.muted(" · no AC yet")
    daily = [n for _, n in ov.daily]
    weekly = [n for _, n in ov.weekly]
    out += [term.section("activity"), _kv([
        ("this week", week),
        ("streak", streak),
        (f"{len(daily)} days", term.s(term.spark(daily), "accent") + term.muted(
            f"  {_plural(sum(daily), 'solve')} on {_plural(sum(1 for n in daily if n), 'day')}")),
        (f"{len(weekly)} weeks", term.s(term.spark(weekly), "accent") + term.muted("  " + " ".join(map(str, weekly)))),
    ], term)]

    # verdicts
    total = sum(ov.verdicts.values())
    out.append(term.section("verdicts") + term.muted(f"  {_plural(total, 'submission')}"))
    if total:
        main = [("OK", "good"), ("WRONG_ANSWER", "bad"), ("TIME_LIMIT_EXCEEDED", "warn"),
                ("RUNTIME_ERROR", "orange"), ("COMPILATION_ERROR", "muted")]
        parts = [term.s(VERDICT_SHORT[v], style) + f" {ov.verdicts[v]}" for v, style in main]
        parts += [term.s(VERDICT_SHORT.get(v, v), "muted") + f" {n}"
                  for v, n in sorted(ov.verdicts.items(), key=lambda x: (-x[1], x[0]))
                  if v not in dict(main)]
        out.append("  " + term.muted(" · ").join(parts))
        if ov.verdicts["OK"]:
            out.append(f"  {ov.wa_per_ac:.2f} WA per AC" + term.muted(" · ")
                       + f"{round(ov.first_try_rate * 100)}% first try" + term.muted(" (solved with no failed attempt)"))
        else:
            out.append("  " + term.muted("no accepted submissions yet"))

    if ov.insights:
        out.append(term.section("insights"))
        for ins in ov.insights[:SHOW_INSIGHTS]:
            out += _insight_lines(ins, term, width)
    out.append("\n" + term.muted("  tags to practise: dojo weak · unsolved from your rounds: dojo upsolve"))
    return "\n".join(out)


def _histogram(by_rating: dict[int, int], term: Term, width: int) -> str:
    """Two aligned rows: ratings 800 … 1600+ and how many you solved at each."""
    counts = Counter()
    for r, n in by_rating.items():
        counts[min(max(r // 100 * 100, HIST_BUCKETS[0]), HIST_BUCKETS[-1])] += n
    labels = [str(b) + ("+" if b == HIST_BUCKETS[-1] else "") for b in HIST_BUCKETS]
    cells = [str(counts[b]) for b in HIST_BUCKETS]
    widths = [max(len(a), len(b)) for a, b in zip(labels, cells)]
    if sum(widths) + 2 * (len(widths) - 1) > width:          # narrow terminal: one line, wrapped
        items = [f"{a}:{b}" for a, b in zip(labels, cells)]
        return "\n".join(textwrap.wrap("  ".join(items), max(20, width)))
    top = "  ".join(term.rating(b, a.rjust(w)) for a, b, w in zip(labels, HIST_BUCKETS, widths))
    bottom = "  ".join(term.s(c.rjust(w), "bold") if c != "0" else term.muted(c.rjust(w))
                       for c, w in zip(cells, widths))
    return top + "\n" + bottom


def _kv(pairs: list[tuple[str, str]], term: Term, indent: int = 2) -> str:
    """term.kv, but a value may span several lines (they line up under the first)."""
    w = max(width_of(k) for k, _ in pairs)
    out = []
    for k, v in pairs:
        first, *rest = v.split("\n")
        out.append(" " * indent + term.s(k.ljust(w), "muted") + "  " + first)
        out += [" " * (indent + w + 2) + line for line in rest]
    return "\n".join(out)


# ---- tags ---------------------------------------------------------------------------------------

@dataclass
class TagStat:
    tag: str
    importance: float      # share of recent problemset problems in the practice band carrying the tag
    solved: int            # your solved problems with the tag (in the band; tags known from the problemset/archive)
    expected: float        # importance * (your solved problems that have tags, in the band)
    failed_attempts: int   # failed judged submissions on problems with the tag (in the band)
    attempts: int          # judged submissions on problems with the tag (in the band)
    avg_rating: float | None   # mean rating of the `solved` problems
    focus: float           # ranking score, higher = practise this more


@dataclass
class TagReport:
    """tag_profile plus the numbers `dojo weak` explains it with."""
    low: int
    high: int
    pool: int              # problemset problems behind `importance`
    tagged_solved: int     # your solved problems in the band with at least one tag
    solved_total: int      # len(snap.all_solved)
    untagged_solved: int   # solved problems whose tags are unknown (any rating)
    untagged_groups: int   # … of them in gyms/groups
    group_tagged: int      # gym/group solves that do have tags (from the solutions archive)
    fail_prior: float      # your fail rate on tagged problems in the band: what tag fail rates shrink toward
    tags: list[TagStat] = field(default_factory=list)


def _contest_id(key: str) -> int:
    m = re.match(r"\d+", key)
    return int(m.group()) if m else 0


def problem_tags(snap: Snapshot, key: str) -> tuple[str, ...]:
    """Tags from the problemset, else your submissions' copy of the problem, else the solutions
    archive (which knows tags for some group problems). '*special' never counts."""
    p = snap.problems.get(key)
    tags: tuple[str, ...] = p.tags if p else ()
    if not tags and key in snap.states:
        tags = next((s.tags for s in reversed(snap.states[key].submissions) if s.tags), ())
    if not tags and key in snap.archive_by_key:
        tags = tuple(snap.archive_by_key[key].get("tags") or ())
    return tuple(sorted({t for t in tags if t not in (SPECIAL, "untagged")}))


def problem_rating(snap: Snapshot, key: str) -> int | None:
    """Rating from the problemset, else your submissions' copy, else the solutions archive."""
    p = snap.problems.get(key)
    if p and p.rating:
        return int(p.rating)
    if key in snap.states:
        r = next((s.rating for s in reversed(snap.states[key].submissions) if s.rating), None)
        if r:
            return int(r)
    a = snap.archive_by_key.get(key)
    try:
        return int(a["rating"]) if a and a.get("rating") else None
    except (TypeError, ValueError):
        return None


def practice_band(snap: Snapshot, low: int | None = None, high: int | None = None) -> tuple[int, int]:
    """[800, max(target_rating, comfort + 300)] unless given."""
    lo = metrics.MIN_RATING if low is None else int(low)
    hi = max(snap.cfg.target_rating, metrics.comfort_rating(snap) + 300) if high is None else int(high)
    if lo > hi:
        raise DojoError(f"rating band {lo}–{hi} is empty — the low end must not exceed the high end")
    return lo, hi


def tag_report(snap: Snapshot, *, low: int | None = None, high: int | None = None) -> TagReport:
    """Per-tag importance, coverage and fail rate in a rating band; see tag_profile for the score."""
    lo, hi = practice_band(snap, low, high)
    pool = [p for p in snap.problems.values()
            if not p.is_gym and p.contest_id >= snap.cfg.min_contest_id and p.rating is not None
            and lo <= p.rating <= hi and SPECIAL not in p.tags]
    share = Counter(t for p in pool for t in set(p.tags))

    def in_band(key: str) -> tuple[str, ...]:
        r = problem_rating(snap, key)
        return problem_tags(snap, key) if r is not None and lo <= r <= hi else ()

    solved, ratings = Counter(), {}
    tagged = untagged = untagged_groups = group_tagged = 0
    for key in snap.all_solved:
        group = _contest_id(key) >= GYM_MIN_ID
        if not problem_tags(snap, key):
            untagged += 1
            untagged_groups += group
            continue
        group_tagged += group
        tags = in_band(key)
        if tags:
            tagged += 1
            solved.update(tags)
            for t in tags:
                ratings.setdefault(t, []).append(problem_rating(snap, key))
    attempts, fails = Counter(), Counter()
    all_judged = all_failed = 0
    for key, st in snap.states.items():
        tags = in_band(key)
        if not tags:
            continue
        judged = st.judged
        failed = sum(s.failed for s in judged)
        all_judged += len(judged)
        all_failed += failed
        for t in tags:
            attempts[t] += len(judged)
            fails[t] += failed
    prior = all_failed / all_judged if all_judged else 0.5

    stats = []
    for t in set(share) | set(solved) | set(attempts):
        importance = share[t] / len(pool) if pool else 0.0
        expected = importance * tagged
        coverage = (solved[t] + 1) / (expected + 1)
        fail = (fails[t] + FAIL_PRIOR * prior) / (attempts[t] + FAIL_PRIOR)
        rs = ratings.get(t)
        stats.append(TagStat(t, importance, solved[t], expected, fails[t], attempts[t],
                             sum(rs) / len(rs) if rs else None, importance * (0.5 + fail) / coverage))
    stats.sort(key=lambda s: (-s.focus, -s.importance, s.tag))
    return TagReport(lo, hi, len(pool), tagged, len(snap.all_solved), untagged, untagged_groups,
                     group_tagged, prior, stats)


def tag_profile(snap: Snapshot, *, low: int | None = None, high: int | None = None) -> list[TagStat]:
    """Which tags to practise, most urgent first.

    Band defaults to [800, max(target_rating, comfort + 300)]. Importance comes from problemset
    problems with contest_id >= cfg.min_contest_id and a rating in the band, excluding '*special'.
    Your side counts your solved / attempted problems rated in the band whose tags are known
    (problemset, else the solutions archive; most group problems have none).

        focus    = importance × (0.5 + fail) / coverage
        coverage = (solved + 1) / (expected + 1)          expected = importance × your tagged solves in the band
        fail     = (failed_attempts + 4·p) / (attempts + 4)   p = your fail rate over all tagged problems in the band

    So a tag twice as common, or with half the coverage, gets twice the focus; your fail rate
    on it moves the score by up to 3× (0.5 → 1.5). The +1s and the 4 pseudo-attempts keep a tag
    you've barely seen from swinging wildly: nothing expected and nothing solved is coverage 1.
    """
    return tag_report(snap, low=low, high=high).tags


def top_focus(stats: list[TagStat], k: int = 3) -> list[str]:
    """The first k tags by focus among those common enough to steer practice (importance >= 5%)."""
    return [s.tag for s in stats if s.importance >= FOCUS_MIN_IMPORTANCE][:max(0, k)]


def focus_tags(snap: Snapshot, k: int = 3) -> list[str]:
    """Top-k tags by focus among tags with importance >= 0.05 — `dojo today` steers its core picks
    to them. Empty when the problemset isn't loaded."""
    return top_focus(tag_profile(snap), k)
