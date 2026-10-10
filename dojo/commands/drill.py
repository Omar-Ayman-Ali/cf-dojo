"""dojo drill — course practice with instant checking and worked solutions."""
from __future__ import annotations

import random
import time

from dojo.commands import add_command
from dojo.context import Ctx
from dojo.drill import core
from dojo.errors import DojoError
from dojo.timeutil import fmt_ago


def register(sub, common):
    p = add_command(sub, common, "drill", "practise a course topic (CIS 203, BSC 201, CIS 208)",
                    description="Practise a course topic with instant checking and worked solutions.\n"
                                "No topic: list topics with your accuracy and a suggestion.\n"
                                "At the answer prompt: ? hint · ! show the solution · q quit.")
    p.add_argument("topic", nargs="*", help="topic key(s), a course code (203, BSC201…), or 'mix'")
    p.add_argument("-n", type=int, default=5, help="number of questions (default 5)")
    p.add_argument("-l", "--level", type=int, default=2, help="difficulty 1–3 (default 2)")
    p.add_argument("--seed", type=int, help="repeat a session exactly")
    p.add_argument("--explain", action="store_true", help="show the worked solution after right answers too")
    p.set_defaults(func=run)


def resolve_topics(words: list[str]) -> list[core.Topic]:
    topics = core.load_topics()
    chosen: list[core.Topic] = []
    for w in words:
        k = w.lower()
        if k in ("mix", "all"):
            chosen += topics.values()
            continue
        if k in topics:
            chosen.append(topics[k])
            continue
        digits = "".join(c for c in k if c.isdigit())
        by_course = [t for t in topics.values() if digits and t.course.replace(" ", "").endswith(digits)]
        if by_course:
            chosen += by_course
            continue
        raise DojoError(f"unknown topic {w!r} — `dojo drill` lists them")
    seen, out = set(), []
    for t in chosen:
        if t.key not in seen:
            seen.add(t.key)
            out.append(t)
    return out


def run(ctx: Ctx) -> int:
    a, term = ctx.args, ctx.term
    if not a.topic:
        return list_topics(ctx)
    topics = resolve_topics(a.topic)
    if a.n < 1:
        raise DojoError("-n must be at least 1")
    seed = a.seed if a.seed is not None else random.randrange(10**6)
    res = core.run_session(topics, n=a.n, level=a.level, rng=random.Random(seed), term=term,
                           state=ctx.state, explain=a.explain)
    if res.asked:
        pct = round(100 * res.correct / res.asked)
        colour = "good" if pct >= 80 else "warn" if pct >= 50 else "bad"
        term.out("", term.s(f"{res.correct}/{res.asked}", colour, "bold") + term.muted(
            f" correct · {pct}% · {res.seconds / res.asked:.0f}s per question · seed {seed}"))
    return 0


def list_topics(ctx: Ctx) -> int:
    term = ctx.term
    topics = core.load_topics()
    st = core.stats(ctx.state)
    now = time.time()
    for course, name in core.COURSES.items():
        rows = []
        for t in topics.values():
            if t.course != course:
                continue
            s = st.get(t.key)
            acc = s.recent_accuracy if s else None
            acc_txt = term.muted("—") if acc is None else term.s(
                f"{round(100 * acc)}%", "good" if acc >= .8 else "warn" if acc >= .5 else "bad")
            last = term.muted(fmt_ago(s.last_ts, now) if s and s.last_ts else "never")
            rows.append([term.s(t.key, "bold"), t.summary, acc_txt, last])
        if rows:
            term.out(term.section(f"{course} · {name}"), term.table(rows, align="llrl"))
    pick = core.suggest(ctx.state, now)
    if pick:
        t, why = pick
        term.out("", term.s("suggested: ", "accent") + term.s(f"dojo drill {t.key}", "bold") + term.muted(f"  ({why})"))
    term.out(term.muted("  mix topics: dojo drill 203 · dojo drill mix -n 10 · check work: dojo solve <topic> …"))
    return 0
