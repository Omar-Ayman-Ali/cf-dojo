"""Statistics drills for CIS 208 Statistical Analysis (Witte & Witte, Statistics).

    freq    frequency, relative %, cumulative % and pie-chart angle from raw data
    center  mean, median and mode (level 3: from a frequency table)
    spread  range, SS, variance and standard deviation — population (÷N) or sample (÷(n−1))
    zscore  z = (X − μ)/σ, the raw score for a z, and which of two scores is relatively better

Arithmetic is exact (Fraction); answers are asked to 2 decimal places and graded with
core.check_number. Solutions are laid out the way the lectures do: the frequency table
(Class | Frequency | Relative % | Cumulative %) and the SS table (X, X − X̄, (X − X̄)²).
"""
from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Sequence

from dojo.drill.core import Question, Topic, Verdict, check_number, fmt_number, norm, parse_number, register
from dojo.term import pad, width_of


# ---- formatting and answer helpers -------------------------------------------------------------

def num(x: Fraction | int | float, places: int = 2) -> str:
    """12 · 6.25 · 2.5 (exact when it has at most `places` decimals), else rounded to `places`."""
    q = Fraction(x)
    if q.denominator == 1:
        return str(q.numerator)
    if (q * 10**places).denominator == 1:
        s = fmt_number(q, places).rstrip("0")
        return s.rstrip(".")
    return fmt_number(q, places)


def approx(x: Fraction | float) -> str:
    """'= 6.25' when exact at 2 decimals, '≈ 2.52' when rounded."""
    q = Fraction(x)
    return ("= " if (q * 100).denominator == 1 else "≈ ") + num(q)


def sqrt_exact(q: Fraction) -> Fraction | float:
    """√q as a Fraction when q is a perfect square of a rational, else a float."""
    if q < 0:
        raise ValueError("negative variance")
    a, b = math.isqrt(q.numerator), math.isqrt(q.denominator)
    if a * a == q.numerator and b * b == q.denominator:
        return Fraction(a, b)
    return math.sqrt(q.numerator / q.denominator)


def _clean(text: str) -> str:
    return re.sub(r"(?i)\s*(°|deg(rees?)?)\s*$", "", text.strip())


def _value_check(want: Fraction | float, *, pct: bool = False, exact: bool = False,
                 what: str = "") -> Callable[[str], Verdict]:
    """check_number with friendlier slips: a proportion given for a percentage, a missing minus."""
    def check(text: str) -> Verdict:
        t = _clean(text)
        v = check_number(t, want, decimals=None if exact else 2, pct=pct)
        if v.ok or v.retry:
            return v
        try:
            got = parse_number(t)
        except (ValueError, ZeroDivisionError):
            return v
        w = Fraction(want)
        if pct and not t.endswith("%") and w and abs(got * 100 - w) <= Fraction(1, 200):
            return Verdict(False, f"that's a proportion; give it as a percentage ({num(got * 100)}%)", retry=True)
        if w < 0 and abs(-got - w) <= Fraction(1, 200):
            return Verdict(False, "check the sign" + (f" of {what}" if what else ""))
        return v
    return check


def read_data(text: str) -> list[Fraction]:
    toks = [t for t in re.split(r"[\s,;]+", text.strip()) if t]
    out = []
    for t in toks:
        try:
            out.append(parse_number(t))
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"{t!r} isn't a number") from None
    return out


def _data_line(values: Sequence, per_row: int = 10) -> list[str]:
    vals = [num(v) if isinstance(v, (int, Fraction)) else str(v) for v in values]
    w = max(len(v) for v in vals)
    return ["  " + "  ".join(v.rjust(w) for v in vals[i:i + per_row]) for i in range(0, len(vals), per_row)]


def _table(header: list[str], rows: list[list[str]], *, total: list[str] | None = None,
           align: str = "") -> list[str]:
    allrows = [header] + rows + ([total] if total else [])
    ncol = len(header)
    align = align or "l" + "r" * (ncol - 1)
    widths = [max(width_of(r[c]) for r in allrows) for c in range(ncol)]

    def fmt(r: list[str]) -> str:
        return "  " + " │ ".join(pad(r[c], widths[c], align[c]) for c in range(ncol)).rstrip()

    rule = "  " + "─┼─".join("─" * w for w in widths)
    out = [fmt(header), rule] + [fmt(r) for r in rows]
    if total:
        out += [rule, fmt(total)]
    return out


# ---- freq ------------------------------------------------------------------------------------------

@dataclass
class FreqTable:
    classes: list                     # in table order
    freq: list[int]
    n: int

    def rel(self, i: int) -> Fraction:
        return Fraction(100 * self.freq[i], self.n)

    def cum(self, i: int) -> Fraction:
        return Fraction(100 * sum(self.freq[:i + 1]), self.n)

    def angle(self, i: int) -> Fraction:
        return Fraction(360 * self.freq[i], self.n)

    def lines(self, angle: bool = False) -> list[str]:
        header = ["Class", "Frequency", "Relative %", "Cumulative %"] + (["Angle"] if angle else [])
        rows = []
        for i, c in enumerate(self.classes):
            rows.append([str(c), str(self.freq[i]), fmt_number(self.rel(i)), fmt_number(self.cum(i))]
                        + ([fmt_number(self.angle(i)) + "°"] if angle else []))
        total = ["Total", str(self.n), "100.00", ""] + (["360.00°"] if angle else [])
        return _table(header, rows, total=total)


def freq_table(data: Sequence, order: Sequence | None = None) -> FreqTable:
    counts = Counter(data)
    if order is None:
        keys = list(counts)
        if all(isinstance(k, (int, Fraction)) for k in keys):
            order = sorted(keys)
        else:
            order = sorted(keys, key=lambda k: (-counts[k], str(k)))
    return FreqTable(list(order), [counts[c] for c in order], len(data))


_CATEGORICAL = [
    ("blood types of {n} donors", ["A", "B", "AB", "O"], [3, 2, 1, 4]),
    ("grades in a quiz of {n} students", ["A", "B", "C", "D", "F"], [2, 4, 5, 3, 1]),
    ("how {n} students get to campus", ["Bus", "Car", "Metro", "Walk"], [4, 2, 3, 1]),
    ("favourite programming language of {n} students", ["C++", "Java", "Python", "JS"], [3, 2, 4, 1]),
    ("T-shirt sizes ordered by {n} students", ["S", "M", "L", "XL"], [2, 4, 3, 1]),
]
_DISCRETE = [
    ("number of siblings of {n} students", 0, 4),
    ("problems solved by {n} contestants in a contest", 0, 6),
    ("goals scored in {n} football matches", 0, 5),
    ("courses failed by {n} students last year", 0, 3),
]


def _sample(rng: random.Random, classes: list, weights: list[int], n: int) -> list:
    """n draws where every class appears at least once."""
    while True:
        data = rng.choices(classes, weights, k=n)
        if set(data) == set(classes):
            return data


@register
class Frequency(Topic):
    key, title, course = "freq", "Frequency tables", "CIS 208"
    summary = "frequency, relative %, cumulative % and pie angles from raw data"
    solve_usage = "A B O AB A O O B … [class=O what=rel|cum|freq|angle]"

    def generate(self, rng: random.Random, level: int) -> Question:
        if level <= 2 or rng.random() < 0.4:
            what_text, classes, weights = rng.choice(_CATEGORICAL)
            n = rng.choice([20, 24, 25, 28, 30, 32, 40] if level >= 2 else [10, 20, 20, 25])
            data = _sample(rng, classes, weights, n)
            order = list(classes)
        else:
            what_text, lo, hi = rng.choice(_DISCRETE)
            n = rng.choice([20, 25, 28, 30, 36, 40])
            classes = list(range(lo, hi + 1))
            weights = [rng.randint(1, 6) for _ in classes]
            data = _sample(rng, classes, weights, n)
            order = classes
        t = freq_table(data, order)
        kinds = {1: ["freq", "rel", "rel"], 2: ["rel", "cum", "angle"], 3: ["cum", "angle", "rel", "atmost"]}[level]
        kind = rng.choice(kinds)
        if kind == "atmost" and not isinstance(order[0], int):
            kind = "cum"
        i = rng.randrange(len(order) - 1 if kind in ("cum", "atmost") else len(order))
        if kind in ("cum", "atmost") and i == 0:
            i = 1
        return self.question(data, t, kind, i, what_text.format(n=n))

    @staticmethod
    def question(data: Sequence, t: FreqTable, kind: str, i: int, context: str) -> Question:
        c = t.classes[i]
        f = t.freq[i]
        order_note = f" (classes in the order {', '.join(map(str, t.classes))})" if kind == "cum" else ""
        if kind == "freq":
            ask, want, pct, exact = f"What is the frequency of {c}?", Fraction(f), False, True
            work = [f"Count the {c}s: f = {f}."]
            expect = "whole number"
        elif kind == "rel":
            ask, want, pct, exact = f"What is the relative frequency of {c}, as a percentage?", t.rel(i), True, False
            work = [f"Relative % = f / n × 100 = {f} / {t.n} × 100 {approx(t.rel(i))}%"]
            expect = "percentage, 2 decimals"
        elif kind == "cum":
            cf = sum(t.freq[:i + 1])
            ask, want, pct, exact = (f"What is the cumulative percentage up to and including {c}{order_note}?",
                                     t.cum(i), True, False)
            parts = " + ".join(str(x) for x in t.freq[:i + 1])
            work = [f"Cumulative frequency up to {c}: {parts} = {cf}",
                    f"Cumulative % = {cf} / {t.n} × 100 {approx(t.cum(i))}%"]
            expect = "percentage, 2 decimals"
        elif kind == "atmost":
            cf = sum(t.freq[:i + 1])
            ask, want, pct, exact = (f"What percentage of the values are at most {c}?", t.cum(i), True, False)
            work = [f"\"At most {c}\" is the cumulative % at {c}: ({' + '.join(str(x) for x in t.freq[:i + 1])}) "
                    f"/ {t.n} × 100 = {cf} / {t.n} × 100 {approx(t.cum(i))}%"]
            expect = "percentage, 2 decimals"
        else:
            ask, want, pct, exact = (f"In a pie chart of this data, what angle does the {c} slice get?",
                                     t.angle(i), False, False)
            work = [f"Angle = 360° × f / n = 360 × {f} / {t.n} {approx(t.angle(i))}°"]
            expect = "degrees, 2 decimals"
        lines = ["Count each class, then build the table:", *t.lines(angle=kind == "angle"), *work]
        return Question(
            prompt="\n".join([f"Data: {context} (n = {t.n}):" if context else f"Data (n = {t.n}):",
                               *_data_line(data), ask]),
            expect=expect, check=_value_check(want, pct=pct, exact=exact),
            answer=(num(want) + ("%" if pct else "°" if kind == "angle" else "")) if not exact else str(f),
            solution="\n".join(lines),
            hint={"freq": "Count how many times it appears.",
                  "rel": "Relative % = frequency / n × 100.",
                  "cum": "Add the frequencies of this class and every class before it, then ÷ n × 100.",
                  "atmost": "Add the frequencies of every value up to it, then ÷ n × 100.",
                  "angle": "Each value is 360° / n of the circle."}[kind])

    def solve(self, text: str) -> Question:
        opts = dict((k.lower(), v) for k, v in re.findall(r"(?i)\b(class|what)\s*=\s*(\S+)", text))
        body = re.sub(r"(?i)\b(class|what)\s*=\s*\S+", " ", text)
        toks = [t for t in re.split(r"[\s,;]+", body.strip()) if t]
        if len(toks) < 2:
            raise ValueError("give the raw data, e.g. A B O AB A O")
        try:
            data: list = [parse_number(t) for t in toks]
            data = [int(x) if x.denominator == 1 else x for x in data]
        except ValueError:
            data = toks
        t = freq_table(data)
        kind = {"freq": "freq", "f": "freq", "frequency": "freq", "rel": "rel", "relative": "rel",
                "cum": "cum", "cumulative": "cum", "angle": "angle", "pie": "angle"}.get(opts.get("what", "rel").lower())
        if kind is None:
            raise ValueError("what= is one of freq, rel, cum, angle")
        if "class" in opts:
            target = opts["class"]
            keys = [str(c) for c in t.classes]
            if target not in keys:
                raise ValueError(f"{target!r} isn't in the data (classes: {', '.join(keys)})")
            return self.question(data, t, kind, keys.index(target), "")
        q = self.question(data, t, "rel", 0, "")
        q.prompt = "\n".join([f"Data (n = {t.n}):", *_data_line(data), "Frequency table:"])
        q.answer = "the table below"
        q.solution = "\n".join(t.lines(angle=True))
        q.check = lambda _text: Verdict(False, "add class=<value> and what=freq|rel|cum|angle to check one number",
                                       retry=True)
        return q


# ---- center ---------------------------------------------------------------------------------------

def median_of(xs: Sequence[Fraction]) -> Fraction:
    s = sorted(xs)
    n = len(s)
    return Fraction(s[n // 2]) if n % 2 else Fraction(s[n // 2 - 1] + s[n // 2], 2)


def modes_of(xs: Sequence) -> list:
    c = Counter(xs)
    top = max(c.values())
    return sorted(k for k, v in c.items() if v == top) if top > 1 else []


def _mean_lines(xs: Sequence[Fraction]) -> list[str]:
    total = sum(xs, Fraction(0))
    terms = " + ".join(num(x) for x in xs) if len(xs) <= 12 else f"(the {len(xs)} values)"
    return [f"ΣX = {terms} = {num(total)}", f"X̄ = ΣX / n = {num(total)} / {len(xs)} {approx(total / len(xs))}"]


def _median_lines(xs: Sequence[Fraction]) -> list[str]:
    s = sorted(xs)
    n = len(s)
    lines = ["Sort the data:", *_data_line(s, 12)]
    if n % 2:
        k = (n + 1) // 2
        lines.append(f"n = {n} is odd: the median is value number (n + 1)/2 = {k}: {num(s[k - 1])}")
    else:
        k = n // 2
        lines.append(f"n = {n} is even: average values {k} and {k + 1}: ({num(s[k - 1])} + {num(s[k])}) / 2 "
                     f"{approx(median_of(s))}")
    return lines


def _mode_lines(xs: Sequence) -> list[str]:
    c = Counter(xs)
    ms = modes_of(xs)
    counts = ", ".join(f"{num(k)}×{v}" for k, v in sorted(c.items()) if v > 1)
    if not ms:
        return ["Every value appears once: there is no mode."]
    if len(ms) == 1:
        return [f"Repeated values: {counts}. The most frequent is {num(ms[0])}, so the mode is {num(ms[0])}."]
    return [f"Repeated values: {counts}. Tied for most frequent: {', '.join(num(m) for m in ms)} (multimodal)."]


def _modes_check(ms: Sequence[Fraction]) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        if norm(text) in ("none", "no mode", "-"):
            got: set = set()
        else:
            try:
                got = set(read_data(text))
            except ValueError as e:
                return Verdict(False, str(e), retry=True)
        if got == set(ms):
            return Verdict(True)
        if not ms:
            return Verdict(False, "no value repeats, so there is no mode")
        if got and got < set(ms):
            return Verdict(False, "there are more modes: give every value tied for most frequent")
        return Verdict(False)
    return check


def _unique_mode_data(rng: random.Random, n: int, lo: int, hi: int) -> list[int]:
    while True:
        xs = [rng.randint(lo, hi) for _ in range(n)]
        c = Counter(xs).most_common()
        if c[0][1] >= 2 and (len(c) == 1 or c[1][1] < c[0][1]):
            return xs


@register
class Center(Topic):
    key, title, course = "center", "Mean, median, mode", "CIS 208"
    summary = "mean, median and mode (level 3: from a frequency table)"
    solve_usage = "4 8 6 5 3 [mean|median|mode] · or a table 1:4 2:5 3:6 (value:frequency)"

    def generate(self, rng: random.Random, level: int) -> Question:
        if level >= 3 and rng.random() < 0.6:
            return self._table_question(rng)
        kind = rng.choice(["mean", "median", "mode"])
        if level <= 1:
            n, lo, hi = rng.choice([5, 7]), 1, 20
        else:
            n, lo, hi = rng.randint(6, 11), 10, 99
        if kind == "mode":
            xs = _unique_mode_data(rng, n, lo, min(hi, lo + n + 3))
        else:
            for _ in range(1000):
                xs = [rng.randint(lo, hi) for _ in range(n)]
                if level >= 2 or sum(xs) % n == 0:
                    break
        return self.data_question([Fraction(x) for x in xs], kind)

    @staticmethod
    def data_question(xs: list[Fraction], kind: str) -> Question:
        data = "\n".join(_data_line(xs, 12))
        if kind == "mean":
            want = sum(xs, Fraction(0)) / len(xs)
            check, answer = _value_check(want), num(want)
            lines, hint = _mean_lines(xs), "Add them all and divide by how many there are."
        elif kind == "median":
            want = median_of(xs)
            check, answer = _value_check(want), num(want)
            lines, hint = _median_lines(xs), "Sort first; with an even count, average the middle two."
        else:
            ms = modes_of(xs)
            check, answer = _modes_check(ms), ", ".join(num(m) for m in ms) or "none"
            lines, hint = _mode_lines(xs), "The value that appears most often."
        return Question(prompt=f"Data (n = {len(xs)}):\n{data}\nFind the {kind}.",
                        expect="number" if kind != "mode" else "value(s), or none",
                        check=check, answer=answer, solution="\n".join(lines), hint=hint)

    def _table_question(self, rng: random.Random) -> Question:
        k = rng.randint(4, 6)
        start = rng.choice([0, 1, 1, 2, 5, 10])
        step = rng.choice([1, 1, 1, 2, 5])
        xs = [start + i * step for i in range(k)]
        while True:
            fs = [rng.randint(1, 12) for _ in xs]
            if sorted(fs)[-1] != sorted(fs)[-2]:
                break
        kind = rng.choices(["mean", "median", "mode"], [6, 3, 1])[0]
        return self.table_question([Fraction(x) for x in xs], fs, kind)

    @staticmethod
    def table_question(xs: list[Fraction], fs: list[int], kind: str) -> Question:
        n = sum(fs)
        fx = [x * f for x, f in zip(xs, fs)]
        cum = [sum(fs[:i + 1]) for i in range(len(fs))]
        expanded = [x for x, f in zip(xs, fs) for _ in range(f)]
        table = _table(["X", "f"], [[num(x), str(f)] for x, f in zip(xs, fs)], align="rr")
        if kind == "mean":
            want = sum(fx, Fraction(0)) / n
            lines = ["Multiply each value by its frequency:",
                     *_table(["X", "f", "fX"], [[num(x), str(f), num(v)] for x, f, v in zip(xs, fs, fx)],
                             total=["", str(n), num(sum(fx, Fraction(0)))], align="rrr"),
                     f"X̄ = ΣfX / Σf = {num(sum(fx, Fraction(0)))} / {n} {approx(want)}"]
            hint = "Mean = ΣfX / Σf: each value counts as many times as its frequency."
            check, answer = _value_check(want), num(want)
        elif kind == "median":
            want = median_of(expanded)
            lines = ["Cumulative frequencies locate the middle:",
                     *_table(["X", "f", "cf"], [[num(x), str(f), str(c)] for x, f, c in zip(xs, fs, cum)],
                             align="rrr")]
            if n % 2:
                k = (n + 1) // 2
                lines.append(f"n = {n}: the median is value number {k}, which falls at X = {num(want)}.")
            else:
                k = n // 2
                a, b = sorted(expanded)[k - 1], sorted(expanded)[k]
                lines.append(f"n = {n}: average values {k} and {k + 1}: ({num(a)} + {num(b)}) / 2 {approx(want)}")
            hint = "Find value number (n + 1)/2 using cumulative frequencies."
            check, answer = _value_check(want), num(want)
        else:
            i = max(range(len(fs)), key=lambda j: fs[j])
            want = xs[i]
            lines = [f"The largest frequency is {fs[i]}, at X = {num(want)}: the mode is {num(want)}."]
            hint = "The value with the largest frequency."
            check, answer = _modes_check([want]), num(want)
        return Question(prompt="\n".join(["Frequency table:", *table, f"Find the {kind}."]),
                        expect="number", check=check, answer=answer, solution="\n".join(lines), hint=hint)

    def solve(self, text: str) -> Question:
        kinds = [k for k in ("mean", "median", "mode") if re.search(rf"(?i)\b{k}\b", text)]
        body = re.sub(r"(?i)\b(mean|median|mode)\b", " ", text)
        if ":" in body:
            pairs = re.findall(r"([-\d./]+)\s*:\s*(\d+)", body)
            if not pairs or re.sub(r"[-\d./]+\s*:\s*\d+|[\s,;]", "", body):
                raise ValueError("write a frequency table as value:frequency pairs, e.g. 1:4 2:5 3:6")
            xs = [parse_number(a) for a, _ in pairs]
            fs = [int(b) for _, b in pairs]
            if sum(fs) == 0:
                raise ValueError("all frequencies are 0")
            kind = kinds[0] if kinds else "mean"
            if kind == "mode" and len(fs) > 1 and sorted(fs)[-1] == sorted(fs)[-2]:
                raise ValueError("two values share the largest frequency: the table is multimodal")
            return self.table_question(xs, fs, kind)
        xs = read_data(body)
        if not xs:
            raise ValueError("give the data, e.g. 4 8 6 5 3")
        if len(kinds) == 1:
            return self.data_question(xs, kinds[0])
        return self._all_question(xs)

    @staticmethod
    def _all_question(xs: list[Fraction]) -> Question:
        mean, med, ms = sum(xs, Fraction(0)) / len(xs), median_of(xs), modes_of(xs)
        wants = {"mean": mean, "median": med}

        def check(text: str) -> Verdict:
            pairs = re.findall(r"(?i)\b(mean|median|mode)\s*[=:]\s*([^\s,;]+(?:\s*,\s*[-\d.]+)*)", text)
            if not pairs:
                return Verdict(False, "label your answers, e.g. mean=5.2 median=5 mode=4", retry=True)
            bad = []
            for k, v in pairs:
                k = k.lower()
                ok = _modes_check(ms)(v) if k == "mode" else check_number(v, wants[k])
                if ok.retry:
                    return ok
                if not ok.ok:
                    bad.append(k)
            return Verdict(not bad, f"check the {', '.join(bad)}" if bad else "")

        lines = ["Mean:", *_mean_lines(xs), "Median:", *_median_lines(xs), "Mode:", *_mode_lines(xs)]
        return Question(
            prompt="\n".join([f"Data (n = {len(xs)}):", *_data_line(xs, 12), "Mean, median and mode:"]),
            expect="mean=… median=… mode=…", check=check,
            answer=f"mean {num(mean)}, median {num(med)}, mode {', '.join(num(m) for m in ms) or 'none'}",
            solution="\n".join(lines))


# ---- spread ---------------------------------------------------------------------------------------

@dataclass
class Spread:
    xs: list[Fraction]
    sample: bool

    @property
    def n(self) -> int:
        return len(self.xs)

    @property
    def mean(self) -> Fraction:
        return sum(self.xs, Fraction(0)) / self.n

    @property
    def ss(self) -> Fraction:
        m = self.mean
        return sum(((x - m) ** 2 for x in self.xs), Fraction(0))

    @property
    def var(self) -> Fraction:
        return self.ss / (self.n - 1 if self.sample else self.n)

    @property
    def sd(self) -> Fraction | float:
        return sqrt_exact(self.var)

    @property
    def range(self) -> Fraction:
        return max(self.xs) - min(self.xs)

    def value(self, stat: str) -> Fraction | float:
        return getattr(self, stat)

    def lines(self, stat: str) -> list[str]:
        xs, m, n = self.xs, self.mean, self.n
        if stat == "range":
            return [f"Range = highest − lowest = {num(max(xs))} − {num(min(xs))} = {num(self.range)}"]
        out = _mean_lines(xs)
        rows = [[num(x), num(x - m), num((x - m) ** 2)] for x in xs]
        out += ["The SS table:",
                *_table(["X", "X − X̄", "(X − X̄)²"], rows,
                        total=[f"Σ {num(sum(xs, Fraction(0)))}", "0", f"SS = {num(self.ss)}"], align="rrr")]
        sq = sum((x * x for x in xs), Fraction(0))
        out.append(f"Check with the computing formula: SS = ΣX² − (ΣX)²/n = {num(sq)} − "
                   f"{num(sum(xs, Fraction(0)))}²/{n} {approx(self.ss)}")
        if stat == "ss":
            return out
        if self.sample:
            out.append(f"Sample variance: s² = SS / (n − 1) = {num(self.ss)} / {n - 1} {approx(self.var)}")
            if stat == "sd":
                out.append(f"Sample standard deviation: s = √s² = √{num(self.var)} {approx(self.sd)}")
        else:
            out.append(f"Population variance: σ² = SS / N = {num(self.ss)} / {n} {approx(self.var)}")
            if stat == "sd":
                out.append(f"Population standard deviation: σ = √σ² = √{num(self.var)} {approx(self.sd)}")
        return out


def _spread_data(rng: random.Random, level: int) -> list[Fraction]:
    for _ in range(5000):
        if level <= 1:
            n, lo, hi = rng.randint(4, 6), 1, 12
        elif level == 2:
            n, lo, hi = rng.randint(5, 7), 2, 20
        else:
            n, lo, hi = rng.randint(8, 10), 45, 99
        xs = [rng.randint(lo, hi) for _ in range(n)]
        s = sum(xs)
        if len(set(xs)) < 3:
            continue
        if level <= 2 and s % n:
            continue                                  # whole-number mean: clean deviations
        if level >= 3 and (10 * s) % n:
            continue                                  # mean with at most 1 decimal
        return [Fraction(x) for x in xs]
    raise RuntimeError("couldn't generate data")


@register
class Variability(Topic):
    key, title, course = "spread", "Range, SS, variance, SD", "CIS 208"
    summary = "range, SS, variance and standard deviation (population or sample)"
    solve_usage = "4 8 6 5 3 sample|population [range|ss|var|sd]"

    def generate(self, rng: random.Random, level: int) -> Question:
        xs = _spread_data(rng, level)
        stat = rng.choice({1: ["range", "ss", "ss", "var"], 2: ["var", "sd", "sd", "ss"],
                           3: ["var", "sd", "sd"]}[level])
        sample = rng.random() < 0.5
        return self.question(Spread(xs, sample), stat)

    @staticmethod
    def question(sp: Spread, stat: str, given: bool = False) -> Question:
        who = "a sample" if sp.sample else "a population"
        if stat == "range":
            ask = "Find the range."
        elif stat == "ss":
            ask = "Find SS, the sum of squared deviations Σ(X − X̄)²."
        elif stat == "var":
            ask = ("Find the sample variance s² (divide by n − 1)." if sp.sample
                   else "Find the population variance σ² (divide by N).")
        else:
            ask = ("Find the sample standard deviation s (divide by n − 1)." if sp.sample
                   else "Find the population standard deviation σ (divide by N).")
        want = sp.value(stat)
        lines = sp.lines(stat)
        slips = {}
        if stat in ("var", "sd"):
            other = Spread(sp.xs, not sp.sample)
            slips[other.value(stat)] = ("that divides by N; a sample divides by n − 1" if sp.sample
                                        else "that divides by n − 1; a population divides by N")
            if stat == "sd":
                slips[sp.var] = "that's the variance; the standard deviation is its square root"
        base = _value_check(want, exact=stat == "range" and Fraction(want).denominator == 1)

        def check(text: str) -> Verdict:
            v = base(text)
            if v.ok or v.retry:
                return v
            for value, msg in slips.items():
                if check_number(_clean(text), value).ok and not check_number(_clean(text), want).ok:
                    return Verdict(False, msg)
            return v

        data = "\n".join(_data_line(sp.xs, 12))
        return Question(
            prompt=f"These {sp.n} scores are {who}{'' if not given else ' (your data)'}:\n{data}\n{ask}"
                   + ("" if stat == "range" else " Give 2 decimal places."),
            expect="number", check=check, answer=num(want), solution="\n".join(lines),
            hint={"range": "Highest minus lowest.",
                  "ss": "Find the mean, subtract it from every score, square, and add up.",
                  "var": "SS divided by " + ("n − 1 (sample)." if sp.sample else "N (population)."),
                  "sd": "The square root of the variance; " + ("sample: SS / (n − 1)." if sp.sample
                                                               else "population: SS / N.")}[stat])

    def solve(self, text: str) -> Question:
        sample = bool(re.search(r"(?i)\bsample\b", text))
        population = bool(re.search(r"(?i)\bpop(ulation)?\b", text))
        words = re.findall(r"(?i)\b(range|ss|var|variance|sd|std)\b", text)
        stat = {"range": "range", "ss": "ss", "var": "var", "variance": "var"}.get(words[-1].lower(), "sd") \
            if words else "sd"
        body = re.sub(r"(?i)\b(sample|population|pop|range|ss|var|variance|sd|std)\b", " ", text)
        xs = read_data(body)
        if len(xs) < 2:
            raise ValueError("give at least two numbers")
        if sample == population:
            raise ValueError("say whether the data is a sample (÷ n − 1) or a population (÷ N)")
        return self.question(Spread(xs, sample), stat, given=True)


# ---- z-scores ---------------------------------------------------------------------------------------

_SUBJECTS = ["Statistics", "Logic Design", "Discrete Math", "OOP", "Databases", "Physics", "Calculus"]


def z_of(x: Fraction, mu: Fraction, sigma: Fraction) -> Fraction:
    return (x - mu) / sigma


def _z_lines(x: Fraction, mu: Fraction, sigma: Fraction) -> list[str]:
    z = z_of(x, mu, sigma)
    return [f"z = (X − μ) / σ = ({num(x)} − {num(mu)}) / {num(sigma)} = {num(x - mu)} / {num(sigma)} {approx(z)}"]


def _which_check(names: tuple[str, str], best: int) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        t = norm(text)
        pick = None
        if t in ("1", "first", "the first"):
            pick = 0
        elif t in ("2", "second", "the second"):
            pick = 1
        else:
            hits = [i for i, nm in enumerate(names) if t and (t in nm.lower() or nm.lower() in t)]
            if len(hits) == 1:
                pick = hits[0]
        if pick is None:
            return Verdict(False, f"answer {names[0]} or {names[1]}", retry=True)
        return Verdict(pick == best)
    return check


@register
class ZScores(Topic):
    key, title, course = "zscore", "z-scores", "CIS 208"
    summary = "z = (X − μ)/σ, raw score from z, which score is relatively better"
    solve_usage = "x=72 mean=65 sd=5 · z=-1.5 mean=65 sd=5 · x=72 mean=65 sd=5 vs x=80 mean=74 sd=8"

    def generate(self, rng: random.Random, level: int) -> Question:
        kind = rng.choice({1: ["z", "z", "raw"], 2: ["z", "raw", "compare"], 3: ["z", "raw", "compare", "compare"]}[level])
        mu = Fraction(rng.choice([50, 60, 65, 70, 72, 75, 80, 100, 500]))
        sigma = Fraction(rng.choice([2, 4, 5, 6, 8, 10, 12, 15, 20]) * (5 if mu >= 500 else 1))
        if kind == "z":
            if level <= 1:
                z = Fraction(rng.choice([-4, -3, -2, -1, 1, 2, 3, 4, 5]), 2)
                x = mu + z * sigma
            else:
                x = mu + rng.randint(-3 * int(sigma), 3 * int(sigma))
                if x == mu:
                    x += 1
            return self.z_question(x, mu, sigma)
        if kind == "raw":
            z = Fraction(rng.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5]), 2) if level <= 1 else \
                Fraction(rng.randint(-250, 250), 100) or Fraction(1, 4)
            return self.raw_question(z, mu, sigma)
        a, b = rng.sample(_SUBJECTS, 2)
        for _ in range(1000):
            m1, m2 = (Fraction(rng.randint(55, 80)) for _ in range(2))
            s1, s2 = (Fraction(rng.choice([4, 5, 6, 8, 10, 12])) for _ in range(2))
            x1, x2 = m1 + rng.randint(-10, 20), m2 + rng.randint(-10, 20)
            z1, z2 = z_of(x1, m1, s1), z_of(x2, m2, s2)
            if abs(z1 - z2) < Fraction(1, 10) or x1 > 100 or x2 > 100:
                continue
            if (x1 > x2) == (z1 > z2) and rng.random() < 0.6:
                continue                              # prefer cases where the raw scores mislead
            break
        return self.compare_question((a, x1, m1, s1), (b, x2, m2, s2))

    @staticmethod
    def z_question(x: Fraction, mu: Fraction, sigma: Fraction) -> Question:
        z = z_of(x, mu, sigma)
        lines = _z_lines(x, mu, sigma)
        lines.append(f"The score is {num(abs(z))} standard deviations {'above' if z > 0 else 'below'} the mean."
                     if z else "The score equals the mean.")
        return Question(
            prompt=f"A population has μ = {num(mu)} and σ = {num(sigma)}. What is the z-score of X = {num(x)}? "
                   "Give 2 decimal places.",
            expect="z, 2 decimals", check=_value_check(z, what="z"), answer=num(z),
            solution="\n".join(lines), hint="z = (X − μ) / σ; below the mean gives a negative z.")

    @staticmethod
    def raw_question(z: Fraction, mu: Fraction, sigma: Fraction) -> Question:
        x = mu + z * sigma
        lines = ["Solve z = (X − μ) / σ for X: X = μ + zσ",
                 f"X = {num(mu)} + ({num(z)})({num(sigma)}) = {num(mu)} + ({num(z * sigma)}) {approx(x)}"]
        return Question(
            prompt=f"A population has μ = {num(mu)} and σ = {num(sigma)}. Which raw score X has z = {num(z)}?",
            expect="number", check=_value_check(x), answer=num(x), solution="\n".join(lines),
            hint="X = μ + zσ.")

    @staticmethod
    def compare_question(first: tuple, second: tuple) -> Question:
        (a, x1, m1, s1), (b, x2, m2, s2) = first, second
        z1, z2 = z_of(x1, m1, s1), z_of(x2, m2, s2)
        best = 0 if z1 > z2 else 1
        lines = [f"{a}: " + _z_lines(x1, m1, s1)[0], f"{b}: " + _z_lines(x2, m2, s2)[0],
                 f"The higher z is {(a, b)[best]} ({num((z1, z2)[best])} vs {num((z1, z2)[1 - best])}): "
                 "it is further above its own class's mean, measured in standard deviations."]
        if (x1 > x2) != (z1 > z2) and x1 != x2:
            lines.append("The raw scores point the other way — that's why you compare z-scores.")
        return Question(
            prompt=(f"Your scores in two exams:\n  {a}: {num(x1)} (class mean {num(m1)}, SD {num(s1)})\n"
                    f"  {b}: {num(x2)} (class mean {num(m2)}, SD {num(s2)})\n"
                    "Relative to each class, which score is better?"),
            expect=f"{a} or {b}", check=_which_check((a, b), best), answer=(a, b)[best],
            solution="\n".join(lines), hint="Turn both into z-scores; the higher z is relatively better.")

    def solve(self, text: str) -> Question:
        parts = [p for p in re.split(r"\s*(?:;|\bvs\b\.?)\s*", text.strip()) if p]
        specs = [self._spec(p) for p in parts]
        if len(specs) == 2:
            for s in specs:
                if "x" not in s:
                    raise ValueError("to compare, give x=, mean= and sd= for both scores")
            return self.compare_question(("Score 1", specs[0]["x"], specs[0]["mean"], specs[0]["sd"]),
                                         ("Score 2", specs[1]["x"], specs[1]["mean"], specs[1]["sd"]))
        if len(specs) != 1:
            raise ValueError("one score, or two separated by ;")
        s = specs[0]
        if "x" in s and "z" in s:
            raise ValueError("give x= (to find z) or z= (to find x), not both")
        if "x" in s:
            return self.z_question(s["x"], s["mean"], s["sd"])
        if "z" in s:
            return self.raw_question(s["z"], s["mean"], s["sd"])
        raise ValueError("give x= (to find z) or z= (to find the raw score)")

    @staticmethod
    def _spec(text: str) -> dict[str, Fraction]:
        keys = {"x": "x", "score": "x", "raw": "x", "z": "z", "mean": "mean", "mu": "mean", "μ": "mean",
                "m": "mean", "sd": "sd", "sigma": "sd", "σ": "sd", "s": "sd", "std": "sd"}
        out: dict[str, Fraction] = {}
        for k, v in re.findall(r"([A-Za-zμσ]+)\s*=\s*([-+\d./]+)", text):
            key = keys.get(k.lower())
            if key is None:
                raise ValueError(f"unknown name {k!r} (use x, z, mean, sd)")
            out[key] = parse_number(v)
        if "mean" not in out or "sd" not in out:
            raise ValueError("give mean= and sd=")
        if out["sd"] <= 0:
            raise ValueError("sd must be positive")
        return out
