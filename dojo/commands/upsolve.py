"""dojo upsolve — problems from your contests you haven't solved."""
from __future__ import annotations

import json
from dataclasses import asdict

from dojo.cf import metrics
from dojo.cf.recommend import problem_text
from dojo.cf.upsolve import RATING_SLACK, contests_taken, upsolve_queue
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.term import pad, truncate, width_of
from dojo.timeutil import fmt_day

DESCRIPTION = f"""\
Unsolved problems from contests you took part in (rated rounds, rounds where you submitted
during the contest, virtual participations), newest contest first. Upsolving the next problem
after the last one you solved in a round is the fastest way to climb.

Shown: problems rated up to your comfort rating + {RATING_SLACK}; unrated ones (fresh rounds) up to two
letters past the furthest problem you solved there. --all shows every unsolved problem."""


def register(sub, common):
    p = add_command(sub, common, "upsolve", "problems from your contests you haven't solved", description=DESCRIPTION)
    p.add_argument("--all", action="store_true", help=f"no rating cap (default: comfort + {RATING_SLACK})")
    p.add_argument("--json", action="store_true", help="print the queue as JSON")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    args, term = ctx.args, ctx.term
    snap = ctx.snapshot()
    snap.require("status", "problemset")
    comfort = metrics.comfort_rating(snap)
    items = upsolve_queue(snap, comfort, uncapped=args.all)

    if args.json:
        term.out(json.dumps(upsolve_rows(snap, items), indent=2, default=str))
        return 0

    taken = contests_taken(snap)
    cap = comfort + RATING_SLACK
    hidden = 0 if args.all else len(upsolve_queue(snap, comfort, uncapped=True)) - len(items)
    if not taken:
        term.out("You haven't taken part in a contest yet. Div. 3, Div. 4 and Educational rounds suit you: "
                 "dojo contests lists the next ones.")
        return 0
    n_contests = len({u.contest_id for u in items})
    scope = "unsolved" if args.all else f"rated up to {cap} (comfort {comfort} + {RATING_SLACK})"
    if not items:
        term.out(f"Nothing to upsolve: every problem {scope} in your {len(taken)} contest"
                 f"{'s' * (len(taken) != 1)} is solved.")
        if hidden:
            term.out(term.muted(f"  {hidden} harder one{'s' * (hidden != 1)}: dojo upsolve --all"))
        return 0

    term.out(term.title("Upsolve") + term.muted(
        f" · {len(items)} problem{'s' * (len(items) != 1)} from {n_contests} contest{'s' * (n_contests != 1)} · {scope}"))
    rated = {r.contest_id: r for r in snap.rating_history}
    name_w = max(20, min(46, term.width - 30))
    key_w = max(len(u.key) for u in items)
    names = {u.key: problem_text(snap, u.key, name_w, key_w) for u in items}
    col = max(width_of(n) for n in names.values())
    shown_cid = None
    for u in items:
        if u.contest_id != shown_cid:
            shown_cid = u.contest_id
            when, how = taken[u.contest_id]
            bits = [term.muted(fmt_day(snap.local_date(when)))]
            r = rated.get(u.contest_id)
            if r:
                bits += [term.muted(f"rank {r.rank}"), term.s(f"{r.delta:+d}", "good" if r.delta >= 0 else "bad")]
            else:
                bits.append(term.muted("virtual" if how == "virtual" else "unrated"))
            title = term.link(truncate(u.contest_name, max(20, term.width - 40)), snap.contest_url(u.contest_id))
            term.out("", term.muted(" · ").join([term.s(title, "bold")] + bits))
        rating = term.rating(u.rating) if u.rating else term.muted("unrated")
        mark = term.s("tried in contest", "warn") if u.attempted else ""
        term.out(("  " + pad(term.link(names[u.key], snap.url(u.key)), col) + "  " + pad(rating, 7, "r")
                  + "  " + mark).rstrip())

    first = items[0].key
    hint = f"start with the first: dojo new {first}"
    if hidden:
        hint += f" · {hidden} harder one{'s' * (hidden != 1)}: dojo upsolve --all"
    term.out("", term.muted("  " + hint))
    return 0


def upsolve_rows(snap, items: list) -> list[dict]:
    """The queue as JSON-ready rows (dojo upsolve --json, dojo web)."""
    return [dict(asdict(u), name=snap.problem(u.key).name, url=snap.url(u.key)) for u in items]
