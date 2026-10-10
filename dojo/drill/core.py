"""Drill framework: topics generate questions, a session asks them, history remembers results.

A topic module defines a Topic subclass and decorates it with @register:

    @register
    class TwosComplement(Topic):
        key, title, course = "twos", "Two's complement arithmetic", "CIS 203"
        summary = "add/subtract n-bit signed numbers, spot overflow"
        solve_usage = "-45 + 23 bits=8"
        def generate(self, rng, level): ... return Question(...)
        def solve(self, text): ... return Question(...)

Questions carry their own checker, so the runner never needs to know the topic's answer format.
"""
from __future__ import annotations

import importlib
import random
import re
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable

TOPIC_MODULES = ["dojo.drill.numbers", "dojo.drill.logic", "dojo.drill.stats"]

COURSES = {
    "CIS 203": "Logic Design",
    "BSC 201": "Discrete Mathematics",
    "CIS 208": "Statistical Analysis",
}


@dataclass
class Verdict:
    ok: bool
    message: str = ""        # feedback for the student: why it's wrong, or a note when right
    retry: bool = False      # the input couldn't be understood: ask again, no penalty


@dataclass
class Question:
    prompt: str                          # the problem, may span lines (tables, truth tables…)
    expect: str                          # input format, shown in the answer prompt: "8-bit binary"
    check: Callable[[str], Verdict]      # grades one typed answer
    answer: str                          # the canonical answer, short
    solution: str                        # worked solution, step by step
    hint: str = ""                       # a nudge that doesn't give the answer away


class Topic:
    key: str = ""
    title: str = ""
    course: str = ""             # one of COURSES
    summary: str = ""            # one line for `dojo drill`
    levels: int = 3              # 1 = warm-up … levels = exam-hard
    solve_usage: str = ""        # input syntax for `dojo solve <key> …`, e.g. 'm(0,2,5) d(7) vars=ABC'

    def generate(self, rng: random.Random, level: int) -> Question:
        raise NotImplementedError

    def solve(self, text: str) -> Question:
        """Calculator mode: the user's own problem. Raise ValueError with a helpful message."""
        raise NotImplementedError


TOPICS: dict[str, Topic] = {}


def register(cls: type[Topic]) -> type[Topic]:
    inst = cls()
    assert inst.key and inst.key not in TOPICS, f"duplicate or empty topic key {inst.key!r}"
    assert inst.course in COURSES, f"{inst.key}: unknown course {inst.course!r}"
    TOPICS[inst.key] = inst
    return cls


def load_topics() -> dict[str, Topic]:
    for m in TOPIC_MODULES:
        importlib.import_module(m)
    return TOPICS


# ---- answer helpers shared by topics ------------------------------------------------------

_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)(e[+-]?\d+)?$", re.I)


def parse_number(text: str) -> Fraction:
    """'3/4', '0.75', '-2', '75%', '1e-3', '3 / 4' -> exact Fraction. ValueError otherwise."""
    t = text.strip().replace(" ", "").replace(",", "")
    if not t:
        raise ValueError("empty answer")
    pct = t.endswith("%")
    if pct:
        t = t[:-1]
    if "/" in t:
        a, _, b = t.partition("/")
        if not (_NUM.match(a) and _NUM.match(b)):
            raise ValueError(f"not a number: {text!r}")
        value = Fraction(a) / Fraction(b)
    elif _NUM.match(t):
        value = Fraction(t)
    else:
        raise ValueError(f"not a number: {text!r}")
    return value / 100 if pct else value


def check_number(text: str, exact: Fraction | float | int, *, decimals: int | None = 2,
                 pct: bool = False) -> Verdict:
    """Right if `text` equals `exact` or rounds to it at `decimals` places (a more precise answer
    within half a unit of the last place also counts). decimals=None demands an exact value.
    pct=True: the expected value is a percentage and '21.43' and '21.43%' both mean 21.43 %."""
    try:
        got = parse_number(text)
    except (ValueError, ZeroDivisionError) as e:
        return Verdict(False, str(e), retry=True)
    if pct and text.strip().endswith("%"):
        got *= 100
    want = Fraction(exact)
    if got == want:
        return Verdict(True)
    if decimals is not None:
        tol = Fraction(1, 2 * 10**decimals) + Fraction(1, 10**9)
        if abs(got - want) <= tol:
            return Verdict(True)
        return Verdict(False, f"expected {fmt_number(want, decimals)}")
    return Verdict(False, f"expected {fmt_fraction(want)}")


def fmt_number(x: Fraction | float, decimals: int = 2) -> str:
    """Rounded half away from zero (how calculators and exams round), trailing zeros kept."""
    q = Fraction(x)
    scaled = abs(q) * 10**decimals
    n = int(scaled + Fraction(1, 2))
    s = f"{n // 10**decimals}" + (f".{n % 10**decimals:0{decimals}d}" if decimals else "")
    return ("-" if q < 0 and n else "") + s


def fmt_fraction(q: Fraction) -> str:
    q = Fraction(q)
    return str(q.numerator) if q.denominator == 1 else f"{q.numerator}/{q.denominator}"


def norm(text: str) -> str:
    """Lower-case, single spaces, stripped — for comparing words like 'tautology'."""
    return " ".join(text.lower().split())


# ---- history -------------------------------------------------------------------------------

@dataclass
class TopicStats:
    key: str
    attempts: int = 0
    correct: int = 0
    last_ts: float | None = None
    recent: list[bool] = field(default_factory=list)      # last 10 results, oldest first

    @property
    def accuracy(self) -> float | None:
        return self.correct / self.attempts if self.attempts else None

    @property
    def recent_accuracy(self) -> float | None:
        return sum(self.recent) / len(self.recent) if self.recent else None


def record(state, topic: str, ok: bool, level: int, seconds: float, now: float | None = None) -> None:
    hist = state.get("drill", [])
    hist.append({"t": round(time.time() if now is None else now), "topic": topic, "ok": ok,
                 "level": level, "sec": round(seconds, 1)})
    del hist[:-5000]                                       # keep the file small
    state.touch("drill")


def stats(state) -> dict[str, TopicStats]:
    out: dict[str, TopicStats] = {}
    for h in state.get("drill", []) or []:
        st = out.setdefault(h["topic"], TopicStats(h["topic"]))
        st.attempts += 1
        st.correct += bool(h["ok"])
        st.last_ts = max(st.last_ts or 0, h["t"])
        st.recent = (st.recent + [bool(h["ok"])])[-10:]
    return out


def suggest(state, now: float | None = None) -> tuple[Topic, str] | None:
    """The topic most worth practising: never tried first, then weakest recent accuracy,
    then longest since practised."""
    topics = load_topics()
    if not topics:
        return None
    now = time.time() if now is None else now
    st = stats(state)
    untried = [t for k, t in topics.items() if k not in st]
    if untried:
        return untried[0], "not practised yet"

    def score(t: Topic) -> tuple[float, float]:
        s = st[t.key]
        return (s.recent_accuracy if s.recent_accuracy is not None else 0.0, s.last_ts or 0)

    best = min(topics.values(), key=score)
    s = st[best.key]
    days = int((now - (s.last_ts or now)) // 86400)
    acc = round(100 * (s.recent_accuracy or 0))
    return best, f"{acc}% on your last {len(s.recent)}" + (f", {days} days ago" if days >= 2 else "")


# ---- interactive session -------------------------------------------------------------------

@dataclass
class SessionResult:
    asked: int = 0
    correct: int = 0
    seconds: float = 0.0
    quit: bool = False


def run_session(topics: list[Topic], *, n: int, level: int, rng: random.Random, term, state,
                input_fn: Callable[[str], str] | None = None, explain: bool = False) -> SessionResult:
    """Ask n questions (cycling through `topics` at random). At the prompt: '?' hint,
    '!' reveal (counts as wrong), 'q' quit."""
    input_fn = input_fn or input          # looked up per call, so tests can patch builtins.input
    res = SessionResult()
    for i in range(n):
        topic = topics[rng.randrange(len(topics))] if len(topics) > 1 else topics[0]
        lvl = max(1, min(level, topic.levels))
        q = topic.generate(rng, lvl)
        term.out("", term.s(f"{topic.course} · {topic.title} · level {lvl} · {i + 1}/{n}", "muted"),
                 q.prompt)
        start = time.monotonic()
        while True:
            try:
                raw = input_fn(term.s(f"{q.expect} › ", "accent"))
            except EOFError:
                res.quit = True
                break
            text = raw.strip()
            if not text:
                continue
            if text.lower() in ("q", "quit", "exit"):
                res.quit = True
                break
            if text == "?":
                term.out(term.s("hint: ", "info") + (q.hint or "no hint for this one — try '!' to see the solution"))
                continue
            if text == "!":
                v = Verdict(False, "revealed")
            else:
                try:
                    v = q.check(text)
                except Exception as e:          # a checker bug must not kill the session
                    v = Verdict(False, f"couldn't check that ({e.__class__.__name__}: {e})", retry=True)
                if v.retry:
                    term.out(term.s("? ", "warn") + (v.message or "couldn't read that") + term.s(f"  (format: {q.expect})", "muted"))
                    continue
            secs = time.monotonic() - start
            res.asked += 1
            res.correct += v.ok
            res.seconds += secs
            record(state, topic.key, v.ok, lvl, secs)
            if v.ok:
                term.out(term.s("✓ correct", "good", "bold") + (f"  {v.message}" if v.message else ""))
                if explain:
                    term.out(_indent(q.solution, term))
            else:
                if v.message and v.message != "revealed":
                    term.out(term.s("✗ ", "bad", "bold") + v.message)
                term.out(term.s("answer: ", "muted") + term.s(q.answer, "bold"), _indent(q.solution, term))
            break
        if res.quit:
            break
    return res


def _indent(text: str, term) -> str:
    return "\n".join("  " + term.s("│ ", "muted") + line for line in text.splitlines())
