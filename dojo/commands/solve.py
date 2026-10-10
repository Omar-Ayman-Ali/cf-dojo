"""dojo solve — work a problem you typed in, step by step (or just check your answer)."""
from __future__ import annotations

from dojo.commands import add_command
from dojo.context import Ctx
from dojo.drill import core
from dojo.errors import DojoError


def register(sub, common):
    p = add_command(sub, common, "solve", "solve or check a course problem you type in",
                    description="Work your own problem step by step.\n"
                                "With --check, only say whether YOUR answer is right (add --reveal to see the solution).\n"
                                "`dojo solve` alone lists the input syntax for every topic.")
    p.add_argument("topic", nargs="?", help="topic key, e.g. kmap, twos, truth, spread")
    p.add_argument("problem", nargs="*", help="the problem, in the topic's syntax")
    p.add_argument("--check", metavar="ANSWER", help="your answer to grade")
    p.add_argument("--reveal", action="store_true", help="with --check: also show the worked solution")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    a, term = ctx.args, ctx.term
    topics = core.load_topics()
    if not a.topic:
        rows = [[term.s(t.key, "bold"), term.muted(t.course), t.solve_usage] for t in topics.values()]
        term.out(term.section("dojo solve <topic> <problem>"), term.table(rows))
        return 0
    t = topics.get(a.topic.lower())
    if not t:
        raise DojoError(f"unknown topic {a.topic!r} — `dojo solve` lists them")
    text = " ".join(a.problem).strip()
    if not text:
        raise DojoError(f"usage: dojo solve {t.key} {t.solve_usage}")
    try:
        q = t.solve(text)
    except ValueError as e:
        raise DojoError(f"{e}\nusage: dojo solve {t.key} {t.solve_usage}") from None
    term.out(q.prompt, "")
    if a.check is not None:
        v = q.check(a.check)
        if v.retry:
            raise DojoError(f"couldn't read your answer: {v.message} (format: {q.expect})")
        if v.ok:
            term.out(term.s("✓ correct", "good", "bold") + (f"  {v.message}" if v.message else ""))
        else:
            term.out(term.s("✗ not quite", "bad", "bold") + (f" — {v.message}" if v.message else ""))
            if q.hint and not a.reveal:
                term.out(term.s("hint: ", "info") + q.hint)
        if not a.reveal:
            return 0 if v.ok else 1
        term.out("")
    term.out(term.s("answer: ", "muted") + term.s(q.answer, "bold"), "", q.solution)
    return 0
