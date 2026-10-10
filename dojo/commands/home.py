"""dojo (no command) — where you stand and what to do next, on one screen."""
from __future__ import annotations

from dojo.commands import add_command
from dojo.context import Ctx
from dojo.drill import core as drill


def register(sub, common):
    p = add_command(sub, common, "home", "overview: rating, streak, today's plan, next contest (same as plain `dojo`)")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    from dojo.cf import analysis, contests, recommend
    term = ctx.term
    # user.info adds nothing the rating history doesn't have here: skip it, one API call fewer.
    snap = ctx.snapshot(("rating", "status", "problemset", "contests", "archive"))
    snap.require("status")
    blocks = [analysis.render_status(analysis.overview(snap), term, compact=True)]

    if "problemset" in snap.loaded:
        plan = recommend.todays_plan(snap, ctx.state)
        blocks += [term.section("today"), recommend.render_plan(plan, snap, term, compact=True)]

    if "contests" in snap.loaded:
        nxt = contests.render_upcoming(contests.upcoming(snap, days=14), term, compact=True)
        if nxt:
            blocks += [term.section("next contest"), nxt]

    pick = drill.suggest(ctx.state)
    if pick:
        topic, why = pick
        blocks += [term.section("course drill"),
                   "  " + term.s(f"dojo drill {topic.key}", "bold") + f"  {topic.title} "
                   + term.muted(f"({topic.course}) · {why}")]

    blocks.append(term.muted("\n  dojo today · dojo weak · dojo upsolve · dojo contests · dojo --help"))
    term.out(*blocks)
    return 0
