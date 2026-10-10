"""dojo sync — refresh every Codeforces dataset now."""
from __future__ import annotations

from dojo.cf.snapshot import ALL
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.timeutil import fmt_ago


QUICK = ("user", "rating", "status")


def register(sub, common):
    p = add_command(sub, common, "sync", "refresh Codeforces data now (commands also refresh what's stale)")
    p.add_argument("--quick", action="store_true",
                   help="only your profile, rating and submissions (3 API calls); the problemset and "
                        "contest list keep their own schedule — what the dojo-sync timer runs")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    if ctx.offline:
        raise DojoError("sync with --offline does nothing")
    if ctx.args.quick:
        ctx.refresh = True
        ctx.snapshot(QUICK)
        ctx.refresh = False
    else:
        ctx.refresh = True
    snap = ctx.snapshot(ALL)
    term = ctx.term
    groups = sum(s.is_gym for s in snap.submissions)
    rows = [
        ["user", f"{snap.handle} · rating {snap.rating if snap.rating is not None else 'unrated'}"],
        ["rating", f"{len(snap.rating_history)} rated contests"],
        ["status", f"{len(snap.submissions)} submissions ({groups} in gyms/groups)"
                   + ("" if snap.authenticated else term.s("  public only — set CF_API_KEY/SECRET for group solves", "warn"))],
        ["problemset", f"{len(snap.problems)} problems"],
        ["contests", f"{len(snap.contests)} contests"],
        ["archive", f"{len(snap.archive)} archived solutions"],
    ]
    missing = [d for d in ALL if d not in snap.loaded]
    for r in rows:
        name = r[0]
        r[0] = term.s(name, "bad" if name in missing else "good")
        if name in snap.fetched_at:
            r.append(term.muted(fmt_ago(snap.fetched_at[name], snap.now_ts)))
    term.out(term.table(rows))
    return 1 if missing else 0
