"""dojo weak — which tags to practise next, from your own solves and failed attempts."""
from __future__ import annotations

import dataclasses
import json
import re
import textwrap

from dojo.cf import analysis
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.term import ARROW, truncate

SHOW_MIN_IMPORTANCE = analysis.SHOW_MIN_IMPORTANCE      # the default table hides rarer tags


def register(sub, common):
    p = add_command(sub, common, "weak", "which tags to practise next",
                    description="Which tags to practise next. For each tag: how often it appears in recent\n"
                                "problemset problems at your level (share), how many you've solved against how\n"
                                "many that share predicts (expected), and how often your submissions on it fail.\n"
                                "focus = share × (0.5 + fail rate) / coverage, coverage = (solved+1)/(expected+1).\n"
                                "Tags come from the problemset; most group problems have none and aren't counted.")
    p.add_argument("--all", action="store_true", help="show every tag, not just the common ones")
    p.add_argument("--band", metavar="LOW-HIGH",
                   help="rating band, e.g. 900-1400 (default: 800 to max(target, comfort + 300))")
    p.add_argument("--json", action="store_true", help="print every tag's numbers as JSON")
    p.set_defaults(func=run)


def parse_band(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-|–|\.\.)\s*(\d+)\s*", text)
    if not m:
        raise DojoError(f"--band {text!r}: expected LOW-HIGH, e.g. --band 900-1400")
    low, high = int(m.group(1)), int(m.group(2))
    if low > high:
        raise DojoError(f"--band {text}: the low end is above the high end")
    return low, high


def run(ctx: Ctx) -> int:
    a, term = ctx.args, ctx.term
    snap = ctx.snapshot()
    snap.require("status", "problemset")
    low, high = parse_band(a.band) if a.band else (None, None)
    rep = analysis.tag_report(snap, low=low, high=high)
    if not rep.pool:
        raise DojoError(f"no problemset problems rated {rep.low}–{rep.high} from contest "
                        f"{snap.cfg.min_contest_id} on — try a wider --band")
    focus = analysis.top_focus(rep.tags)
    if a.json:
        print(json.dumps(report_doc(snap, rep, focus), indent=2, default=str))
        return 0

    width = max(50, term.width)
    band = f"{rep.low}–{rep.high}"
    shown = rep.tags if a.all else [s for s in rep.tags if s.importance >= SHOW_MIN_IMPORTANCE]
    term.out(term.section("tags to practise") + term.muted(f"  rated {band}"),
             term.muted(f"  share: of the {rep.pool} problemset problems rated {band} "
                        f"(contest {snap.cfg.min_contest_id}+), how many carry the tag"),
             term.muted(f"  expected: share × your {rep.tagged_solved} tagged solves rated {band}"), "")

    top = max((s.focus for s in shown), default=0.0) or 1.0
    tag_w = min(max((len(s.tag) for s in shown), default=3), 26)
    bar_w = max(6, min(20, width - (2 + 1 + 2 + tag_w + 7 + 8 + 10 + 11 + 2 * 6)))
    rows = []
    for s in shown:
        fail = (term.s(f"{s.failed_attempts / s.attempts:.0%}", _fail_style(s.failed_attempts / s.attempts))
                + term.muted(f" of {s.attempts}")) if s.attempts else term.muted("—")
        rows.append([
            term.s(ARROW, "accent") if s.tag in focus else " ",
            term.s(truncate(s.tag, tag_w), "bold") if s.tag in focus else truncate(s.tag, tag_w),
            f"{s.importance:.0%}",
            str(s.solved),
            f"{s.expected:.1f}",
            fail,
            term.bar(s.focus / top, bar_w, "warn" if s.tag in focus else "accent"),
        ])
    term.out(term.table(rows, header=["", "tag", "share", "solved", "expected", "fail rate", "focus"],
                        align="llrrrrl"))
    if not a.all and len(shown) < len(rep.tags):
        term.out("  " + term.muted(f"+ {len(rep.tags) - len(shown)} rarer tags (under "
                                   f"{SHOW_MIN_IMPORTANCE:.0%} of problems): dojo weak --all"))

    if focus:
        term.out(term.section("focus next") + "  " + ", ".join(focus))
        stats = {s.tag: s for s in rep.tags}
        w = max(len(t) for t in focus)
        for i, tag in enumerate(focus):
            lines = textwrap.wrap(_reason(stats[tag], rep, first=i == 0), max(30, width - 4 - w))
            term.out(f"  {term.s(tag.ljust(w), 'bold')}  {lines[0]}",
                     *[" " * (4 + w) + line for line in lines[1:]])

    notes = []
    if rep.untagged_solved:
        groups = ("all group problems" if rep.untagged_groups == rep.untagged_solved
                  else f"{rep.untagged_groups} of them group problems")
        notes.append(f"{rep.untagged_solved} of your {rep.solved_total} solved problems have no tags ({groups}), "
                     f"so they aren't counted"
                     + (f"; tags for {rep.group_tagged} group problems come from your solutions archive." if rep.group_tagged
                        else "."))
    if not snap.authenticated:
        notes.append("Only public submissions are visible, so fail rates miss your group training "
                     "(set CF_API_KEY/CF_API_SECRET).")
    if a.band is None and focus:
        notes.append("`dojo today` steers its core problems to these tags, in this order.")
    if notes:
        term.out("")
        for n in notes:
            term.out(*("  " + term.muted(line) for line in textwrap.wrap(n, width - 2)))
    return 0


def report_doc(snap, rep: analysis.TagReport, focus: list[str]) -> dict:
    """The tag report as JSON-ready data (dojo weak --json, dojo web)."""
    stats = {s.tag: s for s in rep.tags}
    return {
        "band": [rep.low, rep.high], "pool": rep.pool, "min_contest_id": snap.cfg.min_contest_id,
        "tagged_solved": rep.tagged_solved, "solved_total": rep.solved_total,
        "untagged_solved": rep.untagged_solved, "untagged_groups": rep.untagged_groups,
        "group_tagged": rep.group_tagged, "fail_prior": round(rep.fail_prior, 4),
        "authenticated": snap.authenticated, "focus": focus,
        "reasons": {t: _reason(stats[t], rep, first=i == 0) for i, t in enumerate(focus)},
        "show_min_importance": SHOW_MIN_IMPORTANCE,
        "tags": [dataclasses.asdict(s) for s in rep.tags],
    }


def _fail_style(rate: float) -> str:
    return "bad" if rate >= 0.6 else "warn" if rate >= 0.4 else "good"


def _reason(s: analysis.TagStat, rep: analysis.TagReport, *, first: bool) -> str:
    where = f"of problems rated {rep.low}–{rep.high}" if first else "of them"
    parts = [f"in {s.importance:.0%} {where}"]
    if rep.tagged_solved:
        parts.append(f"you've solved {s.solved} vs {s.expected:.1f} expected")
    else:
        parts.append("no tagged solves of yours in this band yet")
    if s.attempts >= 5 and s.failed_attempts / s.attempts >= rep.fail_prior + 0.1:
        parts.append(f"{s.failed_attempts} of your {s.attempts} submissions on it failed")
    return "; ".join(parts)
