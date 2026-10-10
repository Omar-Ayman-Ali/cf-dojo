"""Logic drills: propositional logic for BSC 201 Discrete Mathematics and Boolean functions for
CIS 203 Logic Design.

    truth     tautology / contradiction / contingency, or a proposition's truth-table column
    equiv     are two propositions equivalent? (standard laws and their classic near-misses)
    minterms  Σm of an expression
    kmap      minimal sum of products for Σm(…) + d(…)
    simplify  an expression to its minimal sum of products

Everything is computed with dojo.drill.boolexpr; truth tables are compared as bit masks.
Discrete-maths tables use Rosen's row order (all T first); logic-design tables and K-maps use
minterm order and Gray code.
"""
from __future__ import annotations

import random
import re
from typing import Callable, Sequence

from dojo.drill import boolexpr as bx
from dojo.drill.boolexpr import Expr, Implicant, Not, Op, ParseError, Var
from dojo.drill.core import Question, Topic, Verdict, norm, register
from dojo.term import pad, width_of

GRAY = (0, 1, 3, 2)
MAX_TABLE_VARS = 5          # 32 rows: the most a truth table in a solution should show
MAX_KMAP_VARS = 6           # Quine–McCluskey still fine; the map itself is drawn up to 4


# ---- small helpers ----------------------------------------------------------------------------

def _full(n: int) -> int:
    return (1 << (1 << n)) - 1


def _rosen_bits(mask: int, n: int) -> list[bool]:
    """Values in Rosen's row order: the first row has every variable true (minterm 2^n - 1)."""
    top = (1 << n) - 1
    return [bool(mask >> (top - i) & 1) for i in range(1 << n)]


def _assignment(m: int, names: Sequence[str], tf: bool = True) -> str:
    """'p = T, q = F' (tf) or 'A=1 B=0' for minterm m."""
    n = len(names)
    vals = [m >> (n - 1 - i) & 1 for i in range(n)]
    if tf:
        return ", ".join(f"{v} = {'T' if b else 'F'}" for v, b in zip(names, vals))
    return " ".join(f"{v}={b}" for v, b in zip(names, vals))


def minterm_name(m: int, names: Sequence[str]) -> str:
    """'m5 = A'BC'D'."""
    return f"m{m} = {Implicant(len(names), m, 0).to_str(names)}"


def _subst(e: Expr, env: dict[str, Expr]) -> Expr:
    if isinstance(e, Var):
        return env.get(e.name, e)
    if isinstance(e, Not):
        return Not(_subst(e.arg, env))
    if isinstance(e, Op):
        args = tuple(_subst(a, env) for a in e.args)
        if e.kind in ("and", "or", "xor"):
            return bx._nary(e.kind, args)
        return Op(e.kind, args)
    return e


def _degenerate(e: Expr) -> bool:
    """Repeated or complementary operands (p ∧ p, p ↔ ¬p) or ¬¬p: no textbook question has them."""
    if isinstance(e, Not):
        return isinstance(e.arg, Not) or _degenerate(e.arg)
    if isinstance(e, Op):
        if len(set(e.args)) != len(e.args) or any(Not(a) in e.args for a in e.args):
            return True
        return any(_degenerate(a) for a in e.args)
    return False


def _constant_part(e: Expr, names: Sequence[str]) -> bool:
    """A proper compound part that is always T or always F, like ¬p ↔ p inside a bigger formula."""
    full = _full(len(names))
    return any(bx.truth_mask(s, names) in (0, full) for s in bx.subformulas(e)[:-1]
               if isinstance(s, Op))


def _random_expr(rng: random.Random, names: Sequence[str], ops: int, kinds: Sequence[str], *,
                 neg_leaf: float = 0.3, neg_group: float = 0.0) -> Expr:
    """A random tree with `ops` binary operators drawn from `kinds`."""
    if ops == 0:
        v: Expr = Var(rng.choice(names))
        return Not(v) if rng.random() < neg_leaf else v
    left = rng.randint(0, ops - 1)
    a = _random_expr(rng, names, left, kinds, neg_leaf=neg_leaf, neg_group=neg_group)
    b = _random_expr(rng, names, ops - 1 - left, kinds, neg_leaf=neg_leaf, neg_group=neg_group)
    kind = rng.choice(kinds)
    e = bx._nary(kind, (a, b)) if kind in ("and", "or", "xor") else Op(kind, (a, b))
    return Not(e) if rng.random() < neg_group else e


def _parse_answer(text: str, names: Sequence[str]) -> Expr:
    """Parse a typed expression over `names`; lower-case input is accepted for upper-case names."""
    try:
        e = bx.parse(text)
    except ParseError:
        if all(v.isupper() for v in names) and not any(c.isupper() for c in text):
            e = bx.parse(text.upper())
        else:
            raise
    if all(v.isupper() for v in names) and e.vars() and all(v.islower() for v in e.vars()) \
            and {v.upper() for v in e.vars()} <= set(names):
        e = bx.parse(text.upper())
    extra = sorted(e.vars() - set(names))
    if extra:
        raise ValueError(f"{', '.join(extra)} isn't a variable here — use {', '.join(names)}")
    return e


# ---- truth tables ---------------------------------------------------------------------------------

def _columns(targets: Sequence[Expr]) -> list[Expr]:
    cols: dict[Expr, None] = {}
    for t in targets:
        for s in bx.subformulas(t):
            cols.setdefault(s)
    return list(cols)


def _grid(header_rows: list[list[str]], rows: list[list[str]], split: int) -> list[str]:
    """Centre every column; a │ after the first `split` columns (the variables)."""
    ncol = len(rows[0]) if rows else len(header_rows[-1])
    widths = [max(width_of(r[c]) for r in header_rows + rows) for c in range(ncol)]
    out = []
    for r in header_rows + rows:
        cells = [pad(r[c], widths[c], "c") for c in range(ncol)]
        line = "  ".join(cells[:split]) + "  │  " + "   ".join(cells[split:])
        out.append("  " + line.rstrip())
    return out


def discrete_table(targets: Sequence[Expr], names: Sequence[str],
                   titles: dict[Expr, str] | None = None) -> list[str]:
    """A truth table the way Rosen writes one: rows T-first, one column per sub-expression.
    Columns are numbered; a long sub-expression is written with the numbers of earlier columns,
    e.g. '(1) ∧ p'. `titles` puts a name like 'P' over a column instead of its number."""
    titles = titles or {}
    names = list(names)
    n = len(names)
    cols = _columns(targets)
    labels: dict[Expr, str] = {}
    numbers, heads = [], []
    for k, c in enumerate(cols, 1):
        full = bx.render_labeled(c, {})
        heads.append(bx.render_labeled(c, labels))
        numbers.append(titles.get(c, f"({k})"))
        if not bx._is_literal(c) and len(full) > 5:
            labels[c] = f"({k})"
    masks = [bx.truth_mask(c, names) for c in cols]
    rows = []
    for i in range(1 << n):
        m = (1 << n) - 1 - i
        rows.append([("T" if m >> (n - 1 - j) & 1 else "F") for j in range(n)]
                    + [("T" if mk >> m & 1 else "F") for mk in masks])
    return _grid([[""] * n + numbers, names + heads], rows, n)


def design_table(expr: Expr, names: Sequence[str]) -> list[str]:
    """Minterm-order table with 0/1 and a column per sub-expression (logic-design notation)."""
    names = list(names)
    n = len(names)
    cols = _columns([expr])
    masks = [bx.truth_mask(c, names) for c in cols]
    rows = []
    for m in range(1 << n):
        rows.append([str(m)] + [str(m >> (n - 1 - j) & 1) for j in range(n)]
                    + [str(mk >> m & 1) for mk in masks])
    lines = _grid([["m"] + names + [c.to_str() for c in cols]], rows, n + 1)
    return lines


def classify_mask(mask: int, n: int) -> str:
    if mask == _full(n):
        return "tautology"
    if mask == 0:
        return "contradiction"
    return "contingency"


_CLASS_WORDS = {
    "tautology": ("t", "taut", "tautology", "tautologies", "tautological", "always true", "valid"),
    "contradiction": ("c", "contra", "contradiction", "contradictory", "always false", "unsatisfiable"),
    "contingency": ("contingency", "contingent", "cont", "neither", "conting", "sometimes"),
}


def read_class(text: str) -> str:
    t = norm(text).strip(".!")
    for word, forms in _CLASS_WORDS.items():
        if t in forms:
            return word
    for word in _CLASS_WORDS:
        if len(t) >= 4 and word.startswith(t):
            return word
    raise ValueError("answer tautology, contradiction or contingency (t / c / contingency)")


def read_column(text: str, rows: int) -> list[bool]:
    t = re.sub(r"[\s,;|/]", "", text).upper()
    if not t:
        raise ValueError("type the column, like TFTT")
    bad = set(t) - set("TF10")
    if bad:
        raise ValueError(f"use only T and F (or 1 and 0), not {''.join(sorted(bad))!r}")
    if len(t) != rows:
        raise ValueError(f"that's {len(t)} values; the table has {rows} rows")
    return [c in "T1" for c in t]


_YES = {"y", "yes", "equivalent", "equal", "same", "true", "≡", "yes they are"}
_NO = {"n", "no", "not equivalent", "different", "false", "≢", "no they aren't", "not"}


def read_yes_no(text: str) -> bool:
    t = norm(text).strip(".!")
    if t in _YES or t.startswith("yes"):
        return True
    if t in _NO or t.startswith("no"):
        return False
    raise ValueError("answer yes or no")


def _rosen_order(names: Sequence[str]) -> str:
    n = len(names)
    rows = ["".join("T" if not (i >> (n - 1 - j)) & 1 else "F" for j in range(n)) for i in range(1 << n)]
    if n <= 2:
        return ", ".join(rows)
    return ", ".join(rows[:3]) + ", …, " + rows[-1]


# ---- truth: classify or give the column -----------------------------------------------------------

# Classic forms; a, b, c are replaced by variables.
_TAUTOLOGIES = [
    "[(a → b) ∧ a] → b", "[(a → b) ∧ ¬b] → ¬a", "[(a → b) ∧ (b → c)] → (a → c)",
    "[(a ∨ b) ∧ ¬a] → b", "a → (a ∨ b)", "(a ∧ b) → a", "¬(a ∨ b) → ¬a", "(a → b) ∨ (b → a)",
    "[a ∧ (a → b)] → (a ∧ b)", "(a ↔ b) → (a → b)", "[(a → b) ∧ (a → c)] → [a → (b ∧ c)]",
    "(¬a → a) → a", "[(a ∨ b) ∧ (¬a ∨ c)] → (b ∨ c)",
]
_CONTRADICTIONS = [
    "(a → b) ∧ (a ∧ ¬b)", "¬[a → (b → a)]", "(a ↔ b) ∧ (a ↔ ¬b)", "(a ∨ b) ∧ (¬a ∧ ¬b)",
    "¬[(a ∧ b) → a]", "(a ∧ ¬b) ∧ (¬a ∨ b)", "[(a → b) ∧ a] ∧ ¬b",
]


def _truth_vars(n: int) -> list[str]:
    return list("pqrs"[:n])


def _random_prop(rng: random.Random, n: int, level: int, want: str | None) -> Expr:
    """A proposition over n variables using every one of them, of class `want` when given."""
    names = _truth_vars(n)
    kinds = ["and", "or"] if level <= 1 else ["and", "or", "imp", "imp", "iff"]
    ops_range = {1: (2, 3), 2: (3, 4), 3: (4, 6)}[level]
    if want in ("tautology", "contradiction") and level >= 2 and rng.random() < 0.6:
        pool = _TAUTOLOGIES if want == "tautology" else _CONTRADICTIONS
        for _ in range(50):
            tpl = bx.parse(rng.choice(pool))
            k = len(tpl.vars())
            if k > n:
                continue
            chosen = rng.sample(names, k)
            env = {m: Var(v) for m, v in zip("abc", chosen)}
            e = _subst(tpl, env)
            if e.vars() == set(names):
                return e
    for _ in range(4000):
        e = _random_expr(rng, names, rng.randint(*ops_range), kinds, neg_leaf=0.3,
                         neg_group=0.1 if level >= 2 else 0.05)
        if e.vars() != set(names) or _degenerate(e) or _constant_part(e, names):
            continue
        if want is None or classify_mask(bx.truth_mask(e, names), n) == want:
            return e
    raise RuntimeError("couldn't generate a proposition")       # never happens in practice


def truth_solution(e: Expr, names: Sequence[str]) -> list[str]:
    n = len(names)
    mask = bx.truth_mask(e, names)
    cls = classify_mask(mask, n)
    lines = ["Truth table, one column per sub-expression (rows T first):",
             *discrete_table([e], names)]
    col = "".join("T" if b else "F" for b in _rosen_bits(mask, n))
    lines.append(f"Final column, top to bottom: {col}")
    if cls == "tautology":
        lines.append("Every row is T, so it is a tautology.")
    elif cls == "contradiction":
        lines.append("Every row is F, so it is a contradiction.")
    else:
        t = next(m for m in reversed(range(1 << n)) if mask >> m & 1)
        f = next(m for m in reversed(range(1 << n)) if not mask >> m & 1)
        lines.append(f"Some rows are T ({_assignment(t, names)}) and some are F ({_assignment(f, names)}), "
                     "so it is a contingency.")
    return lines


def _class_check(want: str) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        try:
            got = read_class(text)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        return Verdict(got == want)
    return check


def _column_check(mask: int, names: Sequence[str]) -> Callable[[str], Verdict]:
    n = len(names)
    want = _rosen_bits(mask, n)

    def check(text: str) -> Verdict:
        try:
            got = read_column(text, 1 << n)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        wrong = [i for i in range(1 << n) if got[i] != want[i]]
        if not wrong:
            return Verdict(True)
        i = wrong[0]
        m = (1 << n) - 1 - i
        more = f" ({len(wrong)} rows are wrong)" if len(wrong) > 1 else ""
        return Verdict(False, f"row {i + 1} ({_assignment(m, names)}) should be {'T' if want[i] else 'F'}{more}")
    return check


def _either_check(mask: int, names: Sequence[str]) -> Callable[[str], Verdict]:
    """Calculator mode: accept the classification or the column."""
    cls_check = _class_check(classify_mask(mask, len(names)))
    col_check = _column_check(mask, names)

    def check(text: str) -> Verdict:
        if re.fullmatch(r"[\sTFtf01,;|/]+", text) and len(re.sub(r"[\s,;|/]", "", text)) > 1:
            return col_check(text)
        return cls_check(text)
    return check


@register
class TruthTables(Topic):
    key, title, course = "truth", "Truth tables", "BSC 201"
    summary = "tautology, contradiction or contingency; truth-table columns"
    solve_usage = "'(p -> q) & ~q -> ~p'"

    def generate(self, rng: random.Random, level: int) -> Question:
        n = {1: 2, 2: 3, 3: rng.choice([3, 3, 4])}[level]
        if level == 2 and rng.random() < 0.3:
            n = 2
        if rng.random() < 0.6:
            want = rng.choice(["tautology", "contradiction", "contingency"])
            e = _random_prop(rng, n, level, want)
            return self._classify_question(e, _truth_vars(n))
        e = _random_prop(rng, min(n, 3), level, rng.choice([None, None, None, "tautology"]))
        return self._column_question(e, _truth_vars(min(n, 3)))

    @staticmethod
    def _classify_question(e: Expr, names: Sequence[str]) -> Question:
        mask = bx.truth_mask(e, names)
        cls = classify_mask(mask, len(names))
        return Question(
            prompt=f"Is this a tautology, a contradiction or a contingency?\n  {e.to_str('discrete')}",
            expect="tautology/contradiction/contingency", check=_class_check(cls), answer=cls,
            solution="\n".join(truth_solution(e, names)),
            hint="Build the truth table; all T is a tautology, all F a contradiction, a mix a contingency.")

    @staticmethod
    def _column_question(e: Expr, names: Sequence[str]) -> Question:
        mask = bx.truth_mask(e, names)
        col = "".join("T" if b else "F" for b in _rosen_bits(mask, len(names)))
        return Question(
            prompt=(f"Give the final truth-table column of\n  {e.to_str('discrete')}\n"
                    f"rows in the order {', '.join(names)} = {_rosen_order(names)}."),
            expect=f"{1 << len(names)} T/F values, top row first", check=_column_check(mask, names),
            answer=col, solution="\n".join(truth_solution(e, names)),
            hint="Work inside out: one column per sub-expression, then combine them.")

    def solve(self, text: str) -> Question:
        e = bx.parse(text)
        names = sorted(e.vars())
        if len(names) > MAX_TABLE_VARS:
            raise ValueError(f"{len(names)} variables is a {1 << len(names)}-row table; "
                             f"dojo shows up to {MAX_TABLE_VARS}")
        mask = bx.truth_mask(e, names)
        cls = classify_mask(mask, len(names))
        col = "".join("T" if b else "F" for b in _rosen_bits(mask, len(names)))
        return Question(
            prompt=f"Is this a tautology, a contradiction or a contingency?\n  {e.to_str('discrete')}",
            expect="tautology/contradiction/contingency, or the T/F column",
            check=_either_check(mask, names), answer=f"{cls} ({col})",
            solution="\n".join(truth_solution(e, names)))


# ---- equiv -------------------------------------------------------------------------------------------

# (left, right, what it is). Whether a pair is equivalent is always recomputed after substitution.
_LAWS = [
    ("¬(a ∧ b)", "¬a ∨ ¬b", "De Morgan's law"),
    ("¬(a ∨ b)", "¬a ∧ ¬b", "De Morgan's law"),
    ("a → b", "¬b → ¬a", "the contrapositive: an implication is equivalent to its contrapositive"),
    ("b → a", "¬a → ¬b", "the converse and the inverse of a → b are contrapositives of each other"),
    ("a → b", "¬a ∨ b", "the implication law: p → q ≡ ¬p ∨ q"),
    ("¬(a → b)", "a ∧ ¬b", "negating an implication: ¬(p → q) ≡ p ∧ ¬q"),
    ("a ∧ (b ∨ c)", "(a ∧ b) ∨ (a ∧ c)", "the distributive law"),
    ("a ∨ (b ∧ c)", "(a ∨ b) ∧ (a ∨ c)", "the distributive law"),
    ("a ∨ (a ∧ b)", "a", "absorption"),
    ("a ∧ (a ∨ b)", "a", "absorption"),
    ("(a ∧ b) → c", "a → (b → c)", "exportation"),
    ("(a → c) ∧ (b → c)", "(a ∨ b) → c", "a known equivalence: (p → r) ∧ (q → r) ≡ (p ∨ q) → r"),
    ("(a → b) ∧ (a → c)", "a → (b ∧ c)", "a known equivalence: (p → q) ∧ (p → r) ≡ p → (q ∧ r)"),
    ("(a → c) ∨ (b → c)", "(a ∧ b) → c", "a known equivalence: (p → r) ∨ (q → r) ≡ (p ∧ q) → r"),
    ("a ↔ b", "(a → b) ∧ (b → a)", "the biconditional law"),
    ("a ↔ b", "(a ∧ b) ∨ (¬a ∧ ¬b)", "the biconditional law: both true or both false"),
    ("¬(a ↔ b)", "a ↔ ¬b", "negating a biconditional: ¬(p ↔ q) ≡ p ↔ ¬q"),
    ("a ↔ b", "¬a ↔ ¬b", "negating both sides of a biconditional keeps it"),
]
_MISSES = [
    ("¬(a ∧ b)", "¬a ∧ ¬b", "a wrong De Morgan: the ∧ must become ∨"),
    ("¬(a ∨ b)", "¬a ∨ ¬b", "a wrong De Morgan: the ∨ must become ∧"),
    ("a → b", "b → a", "the converse, which is not equivalent to the implication"),
    ("a → b", "¬a → ¬b", "the inverse, which is not equivalent to the implication"),
    ("a → b", "a ∨ ¬b", "a wrong implication law: p → q ≡ ¬p ∨ q, not p ∨ ¬q"),
    ("¬(a → b)", "¬a → ¬b", "not how an implication is negated: ¬(p → q) ≡ p ∧ ¬q"),
    ("a ∧ (b ∨ c)", "(a ∧ b) ∨ c", "a half-done distribution: a must go into both parts"),
    ("a ∨ (b ∧ c)", "(a ∨ b) ∧ c", "a half-done distribution: a must go into both parts"),
    ("a ∨ (a ∧ b)", "a ∧ b", "absorption gives a, not a ∧ b"),
    ("(a ∧ b) → c", "(a → b) → c", "the brackets moved: exportation gives a → (b → c)"),
    ("(a → c) ∧ (b → c)", "(a ∧ b) → c", "∧ of the two implications matches (p ∨ q) → r, not (p ∧ q) → r"),
    ("a ↔ b", "a → b", "only half of the biconditional"),
    ("¬(a ↔ b)", "¬a ↔ ¬b", "negating both sides keeps the biconditional; it doesn't negate it"),
    ("a → (b → c)", "(a → b) → c", "implication isn't associative"),
]


def _law_vars(n: int) -> list[str]:
    return list("pqrs"[:n])


def _make_pair(rng: random.Random, level: int, equivalent: bool) -> tuple[Expr, Expr, str]:
    pool = _LAWS if equivalent else _MISSES
    for _ in range(200):
        left_s, right_s, why = rng.choice(pool)
        left, right = bx.parse(left_s), bx.parse(right_s)
        metas = sorted(left.vars() | right.vars())
        if level <= 1:
            names = _law_vars(len(metas))
            env: dict[str, Expr] = {m: Var(v) for m, v in zip(metas, names)}
        else:
            names = _law_vars(min(4, len(metas) + (1 if level >= 3 else 0)))
            picks = rng.sample(names, len(metas))
            env = {}
            for m, v in zip(metas, picks):
                env[m] = Not(Var(v)) if rng.random() < (0.25 if level == 2 else 0.3) else Var(v)
            if level >= 3:
                spare = [v for v in names if v not in picks]
                if spare:
                    m = rng.choice(metas)
                    kind = rng.choice(["and", "or", "imp"])
                    other = Var(spare[0])
                    env[m] = Op(kind, (env[m], other)) if kind == "imp" else bx._nary(kind, (env[m], other))
        a = bx.strip_double_negation(_subst(left, env))
        b = bx.strip_double_negation(_subst(right, env))
        if a == b:
            continue
        names = sorted(a.vars() | b.vars())
        if (bx.truth_mask(a, names) == bx.truth_mask(b, names)) != equivalent:
            continue
        if rng.random() < 0.5:
            a, b = b, a
        return a, b, why
    raise RuntimeError("couldn't generate a pair")


def equiv_solution(a: Expr, b: Expr, why: str = "") -> tuple[bool, list[str]]:
    names = sorted(a.vars() | b.vars())
    n = len(names)
    ma, mb = bx.truth_mask(a, names), bx.truth_mask(b, names)
    same = ma == mb
    titles = {a: "P", b: "Q"} if a != b else {a: "P = Q"}
    lines = [f"P = {a.to_str('discrete')}", f"Q = {b.to_str('discrete')}",
             "Truth table with both (rows T first):", *discrete_table([a, b], names, titles)]
    if same:
        lines.append("The P and Q columns match in every row, so P ≡ Q.")
    else:
        diff = ma ^ mb
        m = next(m for m in reversed(range(1 << n)) if diff >> m & 1)
        pv, qv = ("T" if ma >> m & 1 else "F"), ("T" if mb >> m & 1 else "F")
        rows = bin(diff).count("1")
        lines.append(f"Counterexample: {_assignment(m, names)} makes P {pv} but Q {qv}"
                     + (f" ({rows} rows differ)." if rows > 1 else "."))
        lines.append("So P and Q are not equivalent.")
    if why:
        lines.append(f"This is {why}." if not why.endswith(".") else f"This is {why}")
    return same, lines


def _yes_no_check(want: bool) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        try:
            got = read_yes_no(text)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        return Verdict(got == want)
    return check


@register
class Equivalence(Topic):
    key, title, course = "equiv", "Logical equivalence", "BSC 201"
    summary = "are two propositions equivalent? laws and classic near-misses"
    solve_usage = "'p -> q ; ~q -> ~p'"

    def generate(self, rng: random.Random, level: int) -> Question:
        a, b, why = _make_pair(rng, level, rng.random() < 0.5)
        return self._question(a, b, why)

    @staticmethod
    def _question(a: Expr, b: Expr, why: str) -> Question:
        same, lines = equiv_solution(a, b, why)
        return Question(
            prompt=f"Are these equivalent?\n  P = {a.to_str('discrete')}\n  Q = {b.to_str('discrete')}",
            expect="yes/no", check=_yes_no_check(same), answer="yes" if same else "no",
            solution="\n".join(lines),
            hint="Look for a row where one side is T and the other F; if there is none, they are equivalent.")

    def solve(self, text: str) -> Question:
        parts = re.split(r"\s*(?:;|≡|==|\bvs\b\.?|\bversus\b)\s*", text.strip())
        parts = [p for p in parts if p]
        if len(parts) != 2:
            raise ValueError("give two propositions separated by ;  e.g. p -> q ; ~q -> ~p")
        a, b = bx.parse(parts[0]), bx.parse(parts[1])
        if len(a.vars() | b.vars()) > MAX_TABLE_VARS:
            raise ValueError(f"at most {MAX_TABLE_VARS} variables")
        return self._question(a, b, "")


# ---- minterms ------------------------------------------------------------------------------------

def read_minterms(text: str, n: int) -> set[int]:
    t = text.strip()
    if norm(t) in ("none", "-", "{}", "∅", "empty"):
        return set()
    t = re.sub(r"(?i)^\s*(?:f\s*=\s*)?(?:σ|∑|sum)?\s*m?\s*\(?", "", t)
    t = re.sub(r"\)\s*$", "", t)
    t = re.sub(r"(?i)\bm(?=\d)", "", t)
    if not re.fullmatch(r"[\d\s,;]*", t):
        raise ValueError("list the minterm numbers, like 1, 3, 6")
    nums = [int(x) for x in re.findall(r"\d+", t)]
    if not nums:
        raise ValueError("list the minterm numbers, like 1, 3, 6")
    top = (1 << n) - 1
    bad = [x for x in nums if x > top]
    if bad:
        raise ValueError(f"m{bad[0]} doesn't exist: {n} variables have minterms 0–{top}")
    return set(nums)


def minterms_solution(e: Expr, names: Sequence[str]) -> list[str]:
    names = list(names)
    ms = bx.minterms(e, names)
    imps = bx.implicants_of(e, names)
    lines: list[str] = []
    if imps is not None and len(names) <= 6:
        lines.append(f"It is a sum of products: each term is 1 on every minterm that matches it "
                     f"({''.join(names)}, '-' = either value).")
        w = max(len(i.to_str(names)) for i in imps)
        for imp in imps:
            covered = imp.minterms()
            lines.append(f"  {imp.to_str(names):<{w}}  {imp.pattern()}  → "
                         + ", ".join(f"m{m}" for m in covered))
        lines.append("Collect them (each minterm once).")
    else:
        lines.append("Truth table, one column per sub-expression:")
        lines += design_table(e, names)
        lines.append("Pick the rows where F = 1.")
    lines.append(f"F = Σm({', '.join(map(str, ms))})" if ms else "F is never 1: no minterms.")
    return lines


def _minterms_check(want: set[int], names: Sequence[str]) -> Callable[[str], Verdict]:
    n = len(names)

    def check(text: str) -> Verdict:
        try:
            got = read_minterms(text, n)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        if got == want:
            return Verdict(True)
        missing, extra = sorted(want - got), sorted(got - want)
        parts = []
        if missing:
            parts.append(f"missing {len(missing)}")
        if extra:
            parts.append(f"{len(extra)} extra")
        m = (missing or extra)[0]
        what = "1" if m in want else "0"
        return Verdict(False, f"{' and '.join(parts)} — e.g. at {minterm_name(m, names)} the expression is {what}")
    return check


def _design_names(n: int) -> list[str]:
    return list("ABCD"[:n])


def _random_design(rng: random.Random, n: int, level: int) -> Expr:
    names = _design_names(n)
    for _ in range(4000):
        if level <= 1 or rng.random() < 0.35:
            terms = []
            for _ in range(rng.randint(2, 3)):
                k = rng.randint(1, min(3, n))
                vs = sorted(rng.sample(names, k))
                terms.append(bx.AND(*(Not(Var(v)) if rng.random() < 0.4 else Var(v) for v in vs)))
            lits = [set(bx._factors(t)) for t in terms]
            if any(i != j and lits[i] <= lits[j] for i in range(len(lits)) for j in range(len(lits))):
                continue                              # AB + ABC: one term swallows another
            e = bx.OR(*terms)
        else:
            kinds = ["and", "or", "and", "or"] + (["xor"] if level >= 2 else [])
            e = _random_expr(rng, names, rng.randint(n - 1, n + 1), kinds, neg_leaf=0.35,
                             neg_group=0.12 if level >= 2 else 0.0)
        if e.vars() != set(names) or _degenerate(e) or _constant_part(e, names):
            continue
        k = len(bx.minterms(e, names))
        if 2 <= k <= (1 << n) - 2:
            return e
    raise RuntimeError("couldn't generate an expression")


@register
class Minterms(Topic):
    key, title, course = "minterms", "Minterms", "CIS 203"
    summary = "list the minterms Σm of an expression"
    solve_usage = "\"AB' + A'(B + C)\" [vars=ABC]"

    def generate(self, rng: random.Random, level: int) -> Question:
        n = 3 if level <= 2 else rng.choice([3, 4, 4])
        if level == 2 and rng.random() < 0.3:
            n = 4
        e = _random_design(rng, n, level)
        return self._question(e, _design_names(n))

    @staticmethod
    def _question(e: Expr, names: Sequence[str]) -> Question:
        ms = bx.minterms(e, names)
        return Question(
            prompt=f"List the minterms of F({', '.join(names)}) = {e.to_str()}",
            expect="minterm numbers, e.g. 1 3 6", check=_minterms_check(set(ms), names),
            answer=", ".join(map(str, ms)) if ms else "none",
            solution="\n".join(minterms_solution(e, names)),
            hint=f"{names[0]} is the most significant bit: m5 with {len(names)} variables is "
                 f"{format(5, f'0{len(names)}b')}.")

    def solve(self, text: str) -> Question:
        text, names = _take_vars(text)
        e = bx.parse(text)
        if names is None:
            names = sorted(e.vars())
        if not names or len(names) > MAX_KMAP_VARS:
            raise ValueError(f"1 to {MAX_KMAP_VARS} variables")
        missing = sorted(e.vars() - set(names))
        if missing:
            raise ValueError(f"vars= leaves out {', '.join(missing)}")
        return self._question(e, names)


def _take_vars(text: str) -> tuple[str, list[str] | None]:
    m = re.search(r"(?i)\bvars?\s*=\s*([A-Za-z,]+)", text)
    if not m:
        return text, None
    names = [c for c in m.group(1) if c.isalpha()]
    if len(set(names)) != len(names):
        raise ValueError("vars= has a repeated letter")
    return text[:m.start()] + text[m.end():], names


# ---- K-maps and minimal SOP -----------------------------------------------------------------------

def kmap_lines(n: int, on: Sequence[int], dc: Sequence[int], names: Sequence[str]) -> list[str]:
    """The map in Gray-code order. 4 variables: rows AB, columns CD; 3: rows A, columns BC."""
    on_s, dc_s = set(on), set(dc)

    def cell(m: int) -> str:
        return "1" if m in on_s else "X" if m in dc_s else "0"

    if n == 2:
        rbits, cbits = 1, 1
    elif n == 3:
        rbits, cbits = 1, 2
    elif n == 4:
        rbits, cbits = 2, 2
    else:
        return []
    rows = [0, 1] if rbits == 1 else list(GRAY)
    cols = [0, 1] if cbits == 1 else list(GRAY)
    rname, cname = "".join(names[:rbits]), "".join(names[rbits:])
    corner = f"{rname}\\{cname}"
    w = max(len(corner), rbits + 1)
    out = ["  " + corner.rjust(w) + "".join(f"  {format(c, f'0{cbits}b'):>2}" for c in cols)]
    for r in rows:
        line = "  " + format(r, f"0{rbits}b").rjust(w)
        for c in cols:
            line += f"  {cell(r << cbits | c):>2}"
        out.append(line)
    return out


def kmap_solution(n: int, on: Sequence[int], dc: Sequence[int], names: Sequence[str]) -> list[str]:
    names = list(names)
    a = bx.analyze(n, on, dc)
    lines: list[str] = []
    if not a.on:
        return ["F has no 1s, so F = 0."]
    if 2 <= n <= 4:
        lines.append("K-map (rows and columns in Gray-code order 00 01 11 10"
                     + ("; X = don't care):" if a.dc else "):"))
        lines += kmap_lines(n, a.on, a.dc, names)
    if len(a.cover) == 1 and a.cover[0].dash == (1 << n) - 1:
        lines.append("Every cell is 1 or X, so F = 1.")
        return lines
    lines.append("Prime implicants (the biggest groups of 1s" + (" and Xs" if a.dc else "") + "):")
    w = max(len(p.to_str(names)) for p in a.primes)
    for p in a.primes:
        cov = [m for m in p.minterms()]
        marks = ", ".join(f"m{m}" + ("(X)" if m in a.dc else "") for m in cov)
        lines.append(f"  {p.to_str(names):<{w}}  {p.pattern()}  covers {marks}")
    if a.essential:
        ess = "; ".join(f"{p.to_str(names)} (only it covers m{a.why_essential[p]})" for p in a.essential)
        lines.append(f"Essential: {ess}.")
    else:
        lines.append("No prime implicant is essential: every 1 is covered by at least two of them.")
    if a.remaining:
        extra = [p for p in a.cover if p not in a.essential]
        left = ", ".join(f"m{m}" for m in a.remaining)
        lines.append(f"Still uncovered: {left}. The cheapest way to cover them: "
                     + " + ".join(p.to_str(names) for p in extra) + ".")
    elif a.essential:
        lines.append("The essential prime implicants already cover every 1.")
    terms, lits = a.cost
    lines.append(f"Minimal SOP: F = {bx.sop_str(a.cover, names)}   ({terms} term{'s' if terms != 1 else ''}, "
                 f"{lits} literal{'s' if lits != 1 else ''})")
    for alt in a.alternatives[:2]:
        lines.append(f"Also minimal: F = {bx.sop_str(alt, names)}")
    return lines


def _sop_check(n: int, on: Sequence[int], dc: Sequence[int], names: Sequence[str]) -> Callable[[str], Verdict]:
    names = list(names)
    on_mask = sum(1 << m for m in on)
    care = _full(n) & ~sum(1 << m for m in dc)
    best = bx.analyze(n, on, dc).cost

    def check(text: str) -> Verdict:
        try:
            e = _parse_answer(text, names)
        except ValueError as err:
            return Verdict(False, str(err), retry=True)
        got = bx.truth_mask(e, names)
        diff = (got ^ on_mask) & care
        if diff:
            m = (diff & -diff).bit_length() - 1
            return Verdict(False, f"you output {got >> m & 1} for {minterm_name(m, names)}; it should be "
                                  f"{on_mask >> m & 1}")
        if not bx.is_sop(e):
            return Verdict(False, "right function — now write it as a sum of products (no brackets)", retry=True)
        terms, lits = bx.cost(e)
        if (terms, lits) > best:
            return Verdict(False, f"correct function, but {terms} terms / {lits} literals; "
                                  f"minimum is {best[0]} / {best[1]}")
        return Verdict(True)
    return check


def _sm(ms: Sequence[int]) -> str:
    return "Σm(" + ", ".join(map(str, ms)) + ")"


def _random_function(rng: random.Random, level: int) -> tuple[int, list[int], list[int]]:
    n = 3 if level <= 1 else 4
    lo, hi = {1: (3, 5), 2: (5, 9), 3: (4, 8)}[level]
    for attempt in range(500):
        on = sorted(rng.sample(range(1 << n), rng.randint(lo, hi)))
        dc: list[int] = []
        if level >= 3:
            rest = [m for m in range(1 << n) if m not in on]
            dc = sorted(rng.sample(rest, rng.randint(2, 4)))
        a = bx.analyze(n, on, dc)
        if len(a.cover) < 2 or len(a.primes) > 8:
            continue
        if level >= 3 and attempt < 400 and bx.analyze(n, on).cost <= a.cost:
            continue                                  # want the don't-cares to matter
        return n, on, dc
    return n, on, dc


@register
class KMap(Topic):
    key, title, course = "kmap", "Karnaugh maps", "CIS 203"
    summary = "minimal sum of products for Σm(…) + d(…)"
    solve_usage = "'m(0,2,5,7) d(1)' [vars=ABCD] · or an expression"

    def generate(self, rng: random.Random, level: int) -> Question:
        n, on, dc = _random_function(rng, level)
        return self.question(n, on, dc, _design_names(n))

    @staticmethod
    def question(n: int, on: Sequence[int], dc: Sequence[int], names: Sequence[str], given: str = "") -> Question:
        a = bx.analyze(n, on, dc)
        spec = given or (_sm(a.on) + (f" + d({', '.join(map(str, a.dc))})" if a.dc else ""))
        return Question(
            prompt=f"Find a minimal sum of products for F({', '.join(names)}) = {spec}",
            expect="SOP expression, e.g. A'B + CD'", check=_sop_check(n, a.on, a.dc, names),
            answer=bx.sop_str(a.cover, names),
            solution="\n".join(kmap_solution(n, a.on, a.dc, names)),
            hint="Draw the map in Gray-code order (00 01 11 10); circle the biggest groups of 1s "
                 "(1, 2, 4, 8 cells, wrapping around the edges)" + ("; Xs may join a group." if a.dc else "."))

    def solve(self, text: str) -> Question:
        text, names = _take_vars(text)
        m = re.search(r"(?i)(?:σ|∑|sum)?\s*m\s*\(([^)]*)\)", text)
        if m:
            on = _int_list(m.group(1))
            d = re.search(r"(?i)\b(?:d|dc|x)\s*\(([^)]*)\)", text)
            dc = _int_list(d.group(1)) if d else []
            top = max(on + dc, default=0)
            if names is None:
                n = max(3, top.bit_length())
                names = list("ABCDEGHI"[:n])         # no F: it names the function
            n = len(names)
            if not 1 <= n <= MAX_KMAP_VARS:
                raise ValueError(f"1 to {MAX_KMAP_VARS} variables")
            if top >= 1 << n:
                raise ValueError(f"m{top} needs more than {n} variables")
            bx._validate(n, on, dc)
            return self.question(n, on, dc, names)
        e = bx.parse(text)
        if names is None:
            names = sorted(e.vars())
        if not 1 <= len(names) <= MAX_KMAP_VARS:
            raise ValueError(f"1 to {MAX_KMAP_VARS} variables")
        missing = sorted(e.vars() - set(names))
        if missing:
            raise ValueError(f"vars= leaves out {', '.join(missing)}")
        on = bx.minterms(e, names)
        q = self.question(len(names), on, [], names, given=e.to_str())
        q.solution = "\n".join([f"F = {_sm(on)}", *q.solution.splitlines()])
        return q


def _int_list(s: str) -> list[int]:
    if not re.fullmatch(r"[\d\s,]*", s):
        raise ValueError(f"can't read the list ({s.strip()}) — use numbers separated by commas")
    return [int(x) for x in re.findall(r"\d+", s)]


# ---- simplify ----------------------------------------------------------------------------------

def _split(imp: Implicant, rng: random.Random) -> list[Implicant]:
    """AB -> ABC + ABC' (split on a variable the group doesn't fix)."""
    free = [i for i in range(imp.n) if imp.dash >> i & 1]
    if not free:
        return [imp]
    bit = 1 << rng.choice(free)
    d = imp.dash & ~bit
    return [Implicant(imp.n, imp.value, d), Implicant(imp.n, imp.value | bit, d)]


def _factor(terms: list[Expr], rng: random.Random) -> list[Expr]:
    """Pull a common literal out of two terms: AB + AC' -> A(B + C')."""
    for _ in range(10):
        if len(terms) < 2:
            return terms
        i, j = rng.sample(range(len(terms)), 2)
        fi, fj = set(bx._factors(terms[i])), set(bx._factors(terms[j]))
        common = sorted(fi & fj, key=str)
        if not common or fi == fj:
            continue
        lit = rng.choice(common)
        ri, rj = [f for f in bx._factors(terms[i]) if f != lit], [f for f in bx._factors(terms[j]) if f != lit]
        if not ri or not rj:
            continue
        merged = bx.AND(lit, bx.OR(bx.AND(*ri), bx.AND(*rj)))
        return [t for k, t in enumerate(terms) if k not in (i, j)] + [merged]
    return terms


def _demorgan(terms: list[Expr], rng: random.Random) -> list[Expr]:
    """Write one product of literals as a negated sum: A'B -> (A + B')'."""
    cands = [k for k, t in enumerate(terms) if isinstance(t, Op) and t.kind == "and"
             and all(bx._is_literal(f) for f in t.args)]
    if not cands:
        return terms
    k = rng.choice(cands)
    inner = bx.OR(*(f.arg if isinstance(f, Not) else Not(f) for f in terms[k].args))
    return terms[:k] + [Not(inner)] + terms[k + 1:]


def _simplify_expr(rng: random.Random, level: int) -> Expr:
    n = {1: rng.choice([2, 3, 3]), 2: 3, 3: rng.choice([3, 4, 4])}[level]
    names = _design_names(n)
    for _ in range(500):
        on = sorted(rng.sample(range(1 << n), rng.randint(2, (1 << n) - 2)))
        a = bx.analyze(n, on)
        if len(a.cover) > 3 or a.cost[1] > 2 * n:
            continue
        imps: list[Implicant] = []
        for p in a.cover:
            imps += _split(p, rng) if rng.random() < 0.7 else [p]
        if level >= 2:                                # a redundant group (a consensus term)
            extra = [p for p in a.primes if p not in a.cover]
            if extra and rng.random() < 0.6:
                imps.append(rng.choice(extra))
        rng.shuffle(imps)
        terms = [p.to_expr(names) for p in imps]
        if level >= 2 and rng.random() < 0.5:
            terms = _factor(terms, rng)
        if level >= 3 and rng.random() < 0.5:
            terms = _demorgan(terms, rng)
        e = bx.OR(*terms)
        if e.vars() != set(names) or _degenerate(e):
            continue
        if bx.truth_mask(e, names) != sum(1 << m for m in on):
            continue
        if bx.is_sop(e) and bx.cost(e) <= a.cost:
            continue
        if _occurrences(e) <= a.cost[1]:
            continue
        return e
    raise RuntimeError("couldn't generate an expression")


def _occurrences(e: Expr) -> int:
    return bx._occurrences(e)


@register
class Simplify(Topic):
    key, title, course = "simplify", "Simplify to minimal SOP", "CIS 203"
    summary = "simplify a Boolean expression to a minimal sum of products"
    solve_usage = "\"A'B'C + A'BC + AB'C + ABC\""

    def generate(self, rng: random.Random, level: int) -> Question:
        e = _simplify_expr(rng, level)
        return self.question(e, sorted(e.vars()))

    @staticmethod
    def question(e: Expr, names: Sequence[str]) -> Question:
        names = list(names)
        n = len(names)
        on = bx.minterms(e, names)
        a = bx.analyze(n, on)
        lines = ["Step 1: find where F is 1.", *minterms_solution(e, names),
                 "Step 2: minimise.", *kmap_solution(n, on, [], names)]
        return Question(
            prompt=f"Simplify to a minimal sum of products:\n  F = {e.to_str()}",
            expect="SOP expression", check=_sop_check(n, on, [], names),
            answer=bx.sop_str(a.cover, names), solution="\n".join(lines),
            hint="List the minterms, put them on a K-map, then take the biggest groups.")

    def solve(self, text: str) -> Question:
        text, names = _take_vars(text)
        e = bx.parse(text)
        if names is None:
            names = sorted(e.vars())
        if not 1 <= len(names) <= MAX_KMAP_VARS:
            raise ValueError(f"1 to {MAX_KMAP_VARS} variables")
        missing = sorted(e.vars() - set(names))
        if missing:
            raise ValueError(f"vars= leaves out {', '.join(missing)}")
        return self.question(e, names)
