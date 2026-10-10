"""dojo retry — attempted-but-unsolved problems and re-solves that are due."""
from __future__ import annotations

import datetime as dt
import json

from dojo.cf.model import make_key, split_key
from dojo.cf.recommend import problem_text
from dojo.cf.snapshot import Snapshot
from dojo.cf.upsolve import (RESOLVE_INTERVALS, RESOLVE_MIN_WRONG, RESOLVE_WINDOW, RetryItem, mark_resolved,
                             retry_queue)
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.term import Term, truncate
from dojo.timeutil import fmt_ago, fmt_day

SHOW_DUE = 10           # due re-solves listed without --all
SHOW_UNSOLVED = 20

DESCRIPTION = f"""\
Two lists of problems to come back to:

  re-solve   problems you solved in the last {RESOLVE_WINDOW} days only after {RESOLVE_MIN_WRONG}+ failed attempts.
             Solve each again from a blank file {RESOLVE_INTERVALS[0]}, {RESOLVE_INTERVALS[1]} and {RESOLVE_INTERVALS[2]} days after the first AC:
             the bug you made once is the one you'll make again. A new AC on/after the due
             day ticks a re-solve off; so does `dojo retry --done <id>`.
  unsolved   problems you submitted and never got accepted, most recent first."""


def register(sub, common):
    p = add_command(sub, common, "retry", "attempted-but-unsolved problems and re-solves that are due",
                    description=DESCRIPTION)
    p.add_argument("--all", action="store_true", help="list everything, including re-solves that aren't due yet")
    p.add_argument("--done", metavar="ID", help="record today's from-scratch re-solve of a problem")
    p.add_argument("--json", action="store_true", help="print the queue as JSON")
    p.set_defaults(func=run)


def short_contest(name: str) -> str:
    """'Codeforces Round 1096 (Div. 3)' -> 'Round 1096 (Div. 3)'."""
    return name.replace("Codeforces Round", "Round").replace("Educational Round", "Educational")


def run(ctx: Ctx) -> int:
    args, term = ctx.args, ctx.term
    snap = ctx.snapshot(("status", "problemset", "contests", "archive"))
    snap.require("status")
    today = snap.today

    if args.done:
        try:
            key = make_key(*split_key(args.done))
        except ValueError as e:
            raise DojoError(str(e)) from None
        nxt = mark_resolved(snap, ctx.state, key, today=today)
        name = f"{key} {snap.problem(key).name}".rstrip()
        if nxt is None:
            term.out(f"Recorded the last re-solve of {name}: it's off the schedule now.")
        else:
            term.out(f"Recorded re-solve {nxt.stage}/{len(RESOLVE_INTERVALS)} of {name}. "
                     f"Next one due {fmt_day(nxt.due)}.")
        return 0

    queue = retry_queue(snap, ctx.state, today=today)
    due = [r for r in queue if r.kind == "resolve" and r.is_due(today)]
    unsolved = [r for r in queue if r.kind == "unsolved"]
    later = [r for r in queue if r.kind == "resolve" and not r.is_due(today)]

    if args.json:
        term.out(json.dumps(retry_rows(snap, due + unsolved + (later if args.all else [])), indent=2, default=str))
        return 0

    show_due = due if args.all else due[:SHOW_DUE]
    show_unsolved = unsolved if args.all else unsolved[:SHOW_UNSOLVED]
    shown = show_due + show_unsolved + (later if args.all else [])
    key_w = max((len(r.key) for r in shown), default=0)
    blocks: list[str] = []
    if due:
        blocks += [term.section(f"re-solve from scratch · {len(due)} due").lstrip("\n"),
                   term.table([_resolve_row(term, snap, r, today, key_w) for r in show_due], align="lrlll")]
        if len(due) > len(show_due):
            blocks.append(term.muted(f"  … {len(due) - len(show_due)} more due: dojo retry --all"))
    if unsolved:
        blocks += [term.section(f"still unsolved · {len(unsolved)}").lstrip("\n" if not blocks else ""),
                   term.table([_unsolved_row(term, snap, r, key_w) for r in show_unsolved], align="lrlll")]
        if len(unsolved) > len(show_unsolved):
            blocks.append(term.muted(f"  … {len(unsolved) - len(show_unsolved)} more: dojo retry --all"))
    if args.all and later:
        blocks += [term.section(f"re-solves coming up · {len(later)}").lstrip("\n" if not blocks else ""),
                   term.table([_resolve_row(term, snap, r, today, key_w) for r in later], align="lrlll")]

    if not blocks:
        if later:
            term.out(f"Nothing to retry today. Next re-solve: {later[0].key} on {fmt_day(later[0].due)} "
                     "(dojo retry --all lists them).")
        else:
            term.out("Nothing to retry: you've solved everything you submitted, and no hard-won solve "
                     "is waiting for a re-solve.")
    else:
        term.out(*blocks)
        hints = []
        if due:
            hints.append("re-solve from a blank file, no peeking · a new AC ticks it off (or dojo retry --done <id>)")
        if unsolved:
            hints.append("one you keep failing: write a brute force, then dojo stress <file>")
        if hints:
            term.out("", *(term.muted("  " + h) for h in hints))
    if not snap.authenticated:
        term.out(term.muted("  only public submissions are visible: add CF_API_KEY/CF_API_SECRET "
                            "to include your group training"))
    return 0


def retry_rows(snap: Snapshot, items: list[RetryItem]) -> list[dict]:
    """Queue entries as JSON-ready rows (dojo retry --json, dojo web)."""
    rows = []
    for r in items:
        p = snap.problem(r.key)
        rows.append({"key": r.key, "kind": r.kind, "name": p.name, "rating": p.rating, "url": snap.url(r.key),
                     "wrong": r.wrong, "last_time": r.last_time, "due": r.due,
                     "stage": r.stage if r.kind == "resolve" else None,
                     "source": short_contest(snap.contest_name(split_key(r.key)[0]))})
    return rows


def _ref(term: Term, snap: Snapshot, key: str, width: int, key_w: int) -> str:
    return term.link(problem_text(snap, key, width, key_w), snap.url(key))


def _rating(term: Term, snap: Snapshot, key: str) -> str:
    r = snap.problem(key).rating
    return term.rating(r) if r else ""


def _resolve_row(term: Term, snap: Snapshot, r: RetryItem, today: dt.date, key_w: int) -> list[str]:
    first = snap.local_date(snap.states[r.key].first_ac.time)
    when = f"solved {fmt_day(first)}" if r.due <= today else f"due {fmt_day(r.due)}"
    return [_ref(term, snap, r.key, max(20, min(40, term.width - 62)), key_w), _rating(term, snap, r.key),
            f"{r.wrong} failed before AC", term.muted(when),
            term.muted(f"re-solve {r.stage + 1}/{len(RESOLVE_INTERVALS)}")]


def _unsolved_row(term: Term, snap: Snapshot, r: RetryItem, key_w: int) -> list[str]:
    width = max(20, min(36, term.width - 64))
    source = short_contest(snap.contest_name(split_key(r.key)[0]))
    return [_ref(term, snap, r.key, width, key_w), _rating(term, snap, r.key),
            term.s(f"{r.wrong} failed", "bad"), term.muted(fmt_ago(r.last_time, snap.now_ts)),
            term.muted(truncate(source, max(16, term.width - width - 40)))]
