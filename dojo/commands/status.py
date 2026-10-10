"""dojo status — rating, progress to target, weekly goal, verdict profile, insights."""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from dojo.cf import analysis
from dojo.commands import add_command
from dojo.context import Ctx


def register(sub, common):
    p = add_command(sub, common, "status", "rating, progress to target, weekly goal, verdict profile",
                    description="Where you stand: rating and the gap to your target, rated rounds, what you've\n"
                                "solved (by rating), this week against your goal, streaks, verdicts, and the\n"
                                "three most useful things to change. --json prints every number and insight.")
    p.add_argument("--json", action="store_true", help="print the overview as JSON")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    snap = ctx.snapshot()
    snap.require("status")
    ov = analysis.overview(snap)
    if ctx.args.json:
        print(json.dumps(to_json(ov), indent=2, default=str))
        return 0
    ctx.term.out(analysis.render_status(ov, ctx.term))
    return 0


def to_json(ov: analysis.Overview) -> dict[str, Any]:
    d = dataclasses.asdict(ov)
    d["target_name"] = analysis.target_name(ov.target)
    d["rating_history"] = [{**dataclasses.asdict(r), "delta": r.delta} for r in ov.rating_history]
    d["daily"] = [{"date": day.isoformat(), "solved": n} for day, n in ov.daily]
    d["weekly"] = [{"week": day.isoformat(), "solved": n} for day, n in ov.weekly]
    d["verdicts"] = dict(ov.verdicts.most_common())
    d["by_rating"] = {str(r): n for r, n in ov.by_rating.items()}
    d["first_try_rate"] = round(ov.first_try_rate, 4)
    d["wa_per_ac"] = round(ov.wa_per_ac, 4)
    return d
