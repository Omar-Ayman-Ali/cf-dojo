"""dojo today — today's practice problems."""
from __future__ import annotations

import datetime as dt
import json

from dojo.cf import recommend
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.timeutil import fmt_day

DESCRIPTION = """\
Today's practice problems, picked around your comfort rating (c: the 75th percentile of the
ratings you solved in the last 90 days, at least your rating - 100).

  warm-up   c-100 … c       a quick win to start
  core      c+100 … c+200   where you improve, steered towards your weak tags
  stretch   c+300 … c+400   hard but within reach
  java      an easy one to solve in Java (on java_days, for CIS 201)
  upsolve   an unsolved problem from a contest you took part in
  retry     a problem you failed, or a hard-won one due for a from-scratch re-solve

Only problems you've never submitted are picked. The plan stays the same all day and solved
problems tick off by themselves (data refreshes every 5 minutes when online)."""


def register(sub, common):
    p = add_command(sub, common, "today", "today's practice problems", description=DESCRIPTION)
    p.add_argument("--reroll", action="store_true", help="replace the problems you haven't solved with new picks")
    p.add_argument("--tags", action="store_true", help="show problem tags (spoilers) and the weak tag behind each core pick")
    p.add_argument("--date", metavar="YYYY-MM-DD", help="show a past day's plan")
    p.add_argument("--json", action="store_true", help="print the plan as JSON")
    p.set_defaults(func=run)


def _day(text: str | None, today: dt.date) -> dt.date:
    if not text:
        return today
    try:
        day = dt.date.fromisoformat(text.strip())
    except ValueError:
        raise DojoError(f"--date {text!r}: use YYYY-MM-DD, e.g. {today.isoformat()}") from None
    if day > today:
        raise DojoError(f"{fmt_day(day)} hasn't come yet — plans are made on the day")
    return day


def run(ctx: Ctx) -> int:
    args, term = ctx.args, ctx.term
    snap = ctx.snapshot()
    snap.require("status")
    day = _day(args.date, snap.today)
    if args.reroll and day != snap.today:
        raise DojoError("--reroll works on today's plan only")
    plan = recommend.todays_plan(snap, ctx.state, day=day, reroll=args.reroll)
    show_tags = args.tags or not ctx.cfg.hide_tags

    if args.json:
        term.out(json.dumps(plan_doc(snap, plan, show_tags=show_tags), indent=2, default=str))
        return 0

    term.out(recommend.render_plan(plan, snap, term, show_tags=show_tags))
    done = sum(recommend.item_done(snap, it, day=plan.day) for it in plan.items)
    if day != snap.today:
        hint = "past plan · solves since then count too"
    elif plan.items and done == len(plan.items):
        hint = "all done — more: dojo upsolve · dojo retry"
    elif not plan.items:
        hint = "nothing fits — try dojo upsolve or dojo retry"
    else:
        hint = "swap one: dojo skip <id> · new set: dojo today --reroll\nwrong answer and no idea why? dojo stress <file> finds a failing test"
    term.out("", term.muted("\n".join("  " + line for line in hint.split("\n"))))
    return 0


def plan_doc(snap, plan: recommend.Plan, *, show_tags: bool) -> dict:
    """The plan as JSON-ready data (dojo today --json, dojo web)."""
    items = []
    for it in plan.items:
        p = snap.problem(it.key)
        d = {"key": it.key, "slot": it.slot, "label": recommend.slot_label(snap, it, plan.day),
             "name": p.name, "rating": it.rating, "url": snap.url(it.key),
             "note": recommend.item_note(snap, it, plan.day),
             "done": recommend.item_done(snap, it, day=plan.day)}
        if show_tags:
            d.update(tags=list(p.tags), focus_tag=it.focus_tag)
        items.append(d)
    return {"day": plan.day, "comfort": plan.comfort, "rerolls": plan.rerolls,
            "done": sum(i["done"] for i in items), "total": len(items), "items": items}
