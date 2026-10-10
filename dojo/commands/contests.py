"""dojo contests — upcoming rounds in your timezone, class clashes flagged."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dojo.cf import contests
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.timeutil import fmt_duration

DESCRIPTION = """\
Upcoming Codeforces rounds in your timezone. Markers:
  ★        suits you: Div. 2, Div. 3, Div. 4, Educational, Div. 1 + Div. 2
  ⚠ what   overlaps a class in your [[schedule]] (config.toml)
  ☾ late   starts between 00:00 and 07:00
Div. 1-only rounds are hidden unless you pass --all.

--ics FILE writes the shown rounds as a calendar file (UTC times, a reminder 30 minutes
before each); importing it again updates the events instead of duplicating them."""


def register(sub, common):
    p = add_command(sub, common, "contests", "upcoming rounds in your timezone, class clashes flagged",
                    description=DESCRIPTION)
    p.add_argument("--days", type=int, default=14, metavar="N", help="look N days ahead (default: 14)")
    p.add_argument("--all", action="store_true", help="include Div. 1-only rounds")
    p.add_argument("--ics", metavar="FILE", help="also write the rounds to an .ics calendar file ('-' = stdout)")
    p.add_argument("--json", action="store_true", help="print the rounds as JSON")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    args, term = ctx.args, ctx.term
    if args.days < 1:
        raise DojoError("--days must be at least 1")
    snap = ctx.snapshot(("contests",))
    snap.require("contests")
    found = contests.upcoming(snap, days=args.days)
    items = found if args.all else [u for u in found if not u.div1_only]
    hidden = len(found) - len(items)

    if args.ics:
        text = contests.to_ics(items, snap.now)
        if args.ics == "-":
            sys.stdout.write(text)
            return 0
        path = Path(args.ics).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, newline="")
        except OSError as e:
            raise DojoError(f"can't write {path}: {e.strerror or e}") from None
        msg = f"Wrote {len(items)} round{'s' * (len(items) != 1)} to {path} (30-minute reminders)."
        if args.json:
            term.note(msg)
        else:
            term.out(msg, "")

    if args.json:
        print(json.dumps([u.to_json() for u in items], indent=2, default=str))
        return 0

    age = snap.now_ts - snap.fetched_at.get("contests", snap.now_ts)
    stale = term.muted(f"  contest list is {fmt_duration(age)} old — dojo sync to refresh") if age > 12 * 3600 else ""
    if not items:
        term.out(f"No rounds in the next {args.days} days"
                 + (f" ({hidden} Div. 1 round{'s' * (hidden != 1)} hidden: --all)." if hidden else "."))
        if args.days < 30:
            term.out(term.muted(f"  dojo contests --days {max(30, args.days * 2)} looks further ahead"))
        if stale:
            term.out(stale)
        return 0

    head = f" · next {args.days} days · {snap.cfg.timezone}"
    term.out(term.title("Contests") + term.muted(head), contests.render_upcoming(items, term), "")
    nxt = next((u for u in items if u.recommended), None)
    if nxt:
        term.out("  " + term.s("Next for you: ", "accent", "bold") + contests.next_words(nxt))
    else:
        term.out(f"  None of these suit a {snap.rating or 'new'} rating; check again in a few days.")

    hints = []
    if hidden:
        hints.append(f"{hidden} Div. 1 round{'s' * (hidden != 1)} hidden: --all")
    if not args.ics:
        hints.append("calendar file: dojo contests --ics contests.ics")
    lines = [term.muted("  " + " · ".join(hints))] if hints else []
    if stale:
        lines.append(stale)
    if lines:
        term.out("", *lines)
    return 0
