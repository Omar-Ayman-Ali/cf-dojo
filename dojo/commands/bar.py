"""dojo bar — one JSON line for a status bar (waybar custom module).

    "custom/dojo": {
        "exec": "dojo bar",
        "return-type": "json",
        "interval": 300,
        "on-click": "xdg-terminal-exec dojo today; read"
    }

Offline by default so the bar never waits on Codeforces; keep the cache fresh with the
dojo-sync timer (contrib/) or by using dojo. CSS classes: idle (nothing solved today),
active (solved something today), done (today's plan finished), stale (data older than a day).
"""
from __future__ import annotations

import json

from dojo.cf import metrics
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.term import next_rank
from dojo.timeutil import fmt_duration, fmt_when

FORMAT = "CF {rating} · {week}/{goal} wk · {done}/{total} today"


def register(sub, common):
    p = add_command(sub, common, "bar", "one-line JSON status for waybar",
                    description=__doc__)
    p.add_argument("--format", default=FORMAT,
                   help="text template; fields: {rating} {to_next} {next_rank} {week} {goal} {done} {total} "
                        "{streak} (default: %(default)r)")
    p.add_argument("--online", action="store_true", help="allow refreshing stale data from Codeforces")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    from dojo.cf import contests, recommend
    if not ctx.args.online:
        ctx.offline = True
    try:
        snap = ctx.snapshot()
        snap.require("user", "status", "problemset")
    except Exception as e:                         # the bar must always print valid JSON
        print(json.dumps({"text": "CF ?", "tooltip": f"dojo: {e}", "class": "stale"}))
        return 0

    plan = recommend.todays_plan(snap, ctx.state)
    done = sum(recommend.item_done(snap, it) for it in plan.items)
    week = len(metrics.solved_this_week(snap))
    streak = metrics.current_streak(snap.ac_days, snap.today)
    nr = next_rank(snap.rating)
    fields = {
        "rating": snap.rating if snap.rating is not None else "unrated",
        "to_next": (nr[0] - snap.rating) if nr and snap.rating is not None else "",
        "next_rank": nr[1].title() if nr else "",
        "week": week, "goal": ctx.cfg.weekly_goal,
        "done": done, "total": len(plan.items),
        "streak": streak,
    }
    try:
        text = ctx.args.format.format(**fields)
    except (KeyError, IndexError, ValueError) as e:
        text = f"dojo: bad --format ({e})"

    tip = [f"{snap.handle} · {fields['rating']}"
           + (f" · {fields['to_next']} to {fields['next_rank']}" if fields["to_next"] != "" else ""),
           f"This week: {week}/{ctx.cfg.weekly_goal} · streak {streak}",
           f"Today: {done}/{len(plan.items)} done"]
    for it in plan.items:
        p = snap.problem(it.key)
        tip.append(f"  {'✓' if recommend.item_done(snap, it) else '○'} {it.key} {p.name} ({it.rating or '?'})")
    if "contests" in snap.loaded:
        nxt = next((u for u in contests.upcoming(snap, days=14) if u.recommended), None)
        if nxt:
            tip.append(f"Next: {nxt.contest.name} · {fmt_when(nxt.start)} "
                       f"(in {fmt_duration(nxt.start.timestamp() - snap.now_ts)})")
    age = snap.now_ts - snap.fetched_at.get("status", snap.now_ts)
    if age > 86400:
        tip.append(f"Data is {fmt_duration(age)} old — run dojo sync")

    klass = ("stale" if age > 86400 else
             "done" if plan.items and done == len(plan.items) else
             "active" if snap.today in set(snap.ac_days) else "idle")
    pct = round(100 * min(1.0, week / ctx.cfg.weekly_goal)) if ctx.cfg.weekly_goal else 0
    print(json.dumps({"text": text, "tooltip": "\n".join(tip), "class": klass, "percentage": pct},
                     ensure_ascii=False))
    return 0
