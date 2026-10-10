"""dojo skip — swap a problem out of today's plan."""
from __future__ import annotations

from dojo.cf import recommend
from dojo.commands import add_command
from dojo.context import Ctx

DESCRIPTION = """\
Swap a problem you haven't solved out of today's plan. The slot gets the next pick by the same
rules (same rating range, same weak tag), and the skipped problem is never planned again."""


def register(sub, common):
    p = add_command(sub, common, "skip", "swap a problem out of today's plan", description=DESCRIPTION)
    p.add_argument("problem", metavar="<id>", help="problem id from `dojo today` (e.g. 2227B), or its position (1, 2, …)")
    p.add_argument("--reason", metavar="R", help="why (kept with the skip in your state file)")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    term = ctx.term
    snap = ctx.snapshot()
    snap.require("status")
    plan, old, new = recommend.skip_item(snap, ctx.state, ctx.args.problem, reason=ctx.args.reason)
    label = recommend.slot_label(snap, old, plan.day)
    gone = f"{old.key} {snap.problem(old.key).name}".rstrip()
    if new:
        p = snap.problem(new.key)
        line = (f"Skipped {gone}. New {label}: " + term.link(f"{new.key} {p.name}".rstrip(), snap.url(new.key))
                + (" " + term.rating(new.rating) if new.rating else ""))
    else:
        line = f"Skipped {gone}. Nothing else fits the {label} slot, so it's gone for today."
    term.out(line, "", recommend.render_plan(plan, snap, term, show_tags=not ctx.cfg.hide_tags))
    return 0
