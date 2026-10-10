"""Boolean expressions for the logic drills: parse both notations, evaluate, print, minimise.

    e = parse("AB' + A'(B + C)")             # logic-design notation
    e = parse("~p & (q -> r)")               # discrete-maths notation, also ¬p ∧ (q → r)
    minterms(e, "ABC")                       # [1, 2, 3, 6]
    minimize(4, [0, 2, 5, 7, 8, 10, 13, 15]) # [B'D', BD]

Operators, loosest binding first: IFF < IMPLIES (right-assoc) < OR < XOR < AND < NOT.

    NOT      postfix ' (also ’ ′ or a combining overline), prefix ~ ! ¬ not
    AND      * · . & && ∧ and, or adjacency (below)
    OR       + | || ∨ or
    XOR      ⊕ ⊻ xor
    IMPLIES  -> → => ⇒ implies
    IFF      <-> ↔ <=> ⇔ iff
    constants 0 1 true false ⊤ ⊥, brackets ( ) [ ] { }, whole-word keywords in any case

Variables are single letters. Adjacency means AND only between uppercase operands: AB'C, A(B + C),
(A + B)(C + D). Next to a lowercase variable it is an error, and so is a run of lowercase letters
that isn't a keyword (`pq`): in discrete-maths notation a missing operator is a typo, and `p v q`
must never quietly mean p ∧ v ∧ q. In an expression with lowercase variables a standalone T or F is
the constant true / false (Rosen's notation). `^` is rejected: it means AND to some people and XOR
to others. A leading `F =` or `F(A,B,C) =` is ignored, so answers can be written as equations.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from dojo.term import width_of

MAX_LEN = 2000          # characters in one expression
MAX_DEPTH = 60          # nested brackets, NOTs and implications
MAX_VARS = 8            # truth tables and minimisation (256 rows)
DEFAULT_NAMES = "ABCDEFGH"


class ParseError(ValueError):
    """A bad expression. str() is the message, the text, and a caret under the offending spot."""

    def __init__(self, message: str, text: str, pos: int):
        self.message, self.text, self.pos = message, text, pos
        shown = re.sub(r"\s", " ", text)
        caret = " " * width_of(shown[:max(0, min(pos, len(shown)))]) + "^"
        super().__init__(f"{message}\n  {shown}\n  {caret}")


# ---- AST ------------------------------------------------------------------------------------

class Expr:
    """A Boolean expression. Nodes are immutable and compare by structure."""

    def eval(self, env: Mapping[str, object]) -> bool:
        raise NotImplementedError

    def vars(self) -> frozenset[str]:
        raise NotImplementedError

    def to_str(self, style: str = "design") -> str:
        """'design': A'B + C(D ⊕ A).  'discrete': (¬p ∧ q) ∨ r, with Rosen's [ ] for outer brackets.
        Either output parses back to the same function."""
        if style == "design":
            return _design(self)
        if style == "discrete":
            return _discrete(self, _has_lower(self), {})
        raise ValueError(f"unknown style {style!r} (use 'design' or 'discrete')")

    def __str__(self) -> str:
        return self.to_str()


@dataclass(frozen=True)
class Const(Expr):
    value: bool

    def eval(self, env: Mapping[str, object]) -> bool:
        return self.value

    def vars(self) -> frozenset[str]:
        return frozenset()


@dataclass(frozen=True)
class Var(Expr):
    name: str

    def eval(self, env: Mapping[str, object]) -> bool:
        try:
            return bool(env[self.name])
        except KeyError:
            raise KeyError(f"no value for variable {self.name}") from None

    def vars(self) -> frozenset[str]:
        return frozenset((self.name,))


@dataclass(frozen=True)
class Not(Expr):
    arg: Expr

    def eval(self, env: Mapping[str, object]) -> bool:
        return not self.arg.eval(env)

    def vars(self) -> frozenset[str]:
        return self.arg.vars()


@dataclass(frozen=True)
class Op(Expr):
    kind: str                     # and | or | xor (n-ary, flattened) · imp | iff (binary)
    args: tuple[Expr, ...]

    def eval(self, env: Mapping[str, object]) -> bool:
        vals = [a.eval(env) for a in self.args]
        if self.kind == "and":
            return all(vals)
        if self.kind == "or":
            return any(vals)
        if self.kind == "xor":
            return sum(vals) % 2 == 1
        if self.kind == "imp":
            return (not vals[0]) or vals[1]
        if self.kind == "iff":
            return vals[0] == vals[1]
        raise ValueError(f"unknown operator {self.kind!r}")

    def vars(self) -> frozenset[str]:
        return frozenset().union(*(a.vars() for a in self.args))


TRUE, FALSE = Const(True), Const(False)


def NOT(x: Expr) -> Expr:
    return Not(x)


def AND(*args: Expr) -> Expr:
    return _nary("and", args)


def OR(*args: Expr) -> Expr:
    return _nary("or", args)


def XOR(*args: Expr) -> Expr:
    return _nary("xor", args)


def IMP(a: Expr, b: Expr) -> Expr:
    return Op("imp", (a, b))


def IFF(a: Expr, b: Expr) -> Expr:
    return Op("iff", (a, b))


def _nary(kind: str, args: Iterable[Expr]) -> Expr:
    flat: list[Expr] = []
    for a in args:
        flat.extend(a.args if isinstance(a, Op) and a.kind == kind else (a,))
    if not flat:
        raise ValueError(f"{kind} needs at least one operand")
    return flat[0] if len(flat) == 1 else Op(kind, tuple(flat))


def _has_lower(e: Expr) -> bool:
    return any(v.islower() for v in e.vars())


def strip_double_negation(e: Expr) -> Expr:
    """¬¬x -> x everywhere (same function, easier to read)."""
    if isinstance(e, Not):
        inner = strip_double_negation(e.arg)
        return inner.arg if isinstance(inner, Not) else Not(inner)
    if isinstance(e, Op):
        args = tuple(strip_double_negation(a) for a in e.args)
        return _nary(e.kind, args) if e.kind in ("and", "or", "xor") else Op(e.kind, args)
    return e


def subformulas(e: Expr) -> list[Expr]:
    """Distinct compound sub-expressions, innermost first (post-order), ending with `e` itself.
    The columns a student writes in a truth table. Variables and constants are left out."""
    seen: dict[Expr, None] = {}

    def walk(x: Expr) -> None:
        if isinstance(x, Not):
            walk(x.arg)
        elif isinstance(x, Op):
            for a in x.args:
                walk(a)
        else:
            return
        seen.setdefault(x)

    walk(e)
    return list(seen)


# ---- printing -----------------------------------------------------------------------------

_DSYM = {"and": " ∧ ", "or": " ∨ ", "xor": " ⊕ ", "imp": " → ", "iff": " ↔ "}
_WRAP_DESIGN = {            # operand kinds that need brackets inside each operator (design style)
    "and": {"or", "xor", "imp", "iff"},
    "or": {"xor", "imp", "iff"},           # xor inside + gets brackets for clarity
    "xor": {"or", "imp", "iff"},
    "imp": {"and", "or", "xor", "imp", "iff"},
    "iff": {"and", "or", "xor", "imp", "iff"},
}


def _design(e: Expr) -> str:
    if isinstance(e, Const):
        return "1" if e.value else "0"
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Not):
        inner = _design(e.arg)
        return inner + "'" if isinstance(e.arg, (Var, Const, Not)) else f"({inner})'"
    assert isinstance(e, Op)
    parts = [f"({_design(a)})" if isinstance(a, Op) and a.kind in _WRAP_DESIGN[e.kind] else _design(a)
             for a in e.args]
    if e.kind != "and":
        return {"or": " + ", "xor": " ⊕ ", "imp": " → ", "iff": " ↔ "}[e.kind].join(parts)
    # Adjacency, except where the parser would refuse it or misread it.
    out = parts[0]
    for prev, arg, part in zip(e.args, e.args[1:], parts[1:]):
        sep = ""
        if _has_lower(prev) or _has_lower(arg) or (out[-1].isdigit() and part[0].isdigit()):
            sep = "·"
        out += sep + part
    if any(w.lower() in _KEYWORDS for w in re.findall(r"[A-Za-z]{2,}", out)):
        out = "·".join(parts)                   # e.g. N·O·T, not the keyword NOT
    return out


def _discrete(e: Expr, tf: bool, labels: Mapping[Expr, str]) -> str:
    """tf: print constants as T / F (only when lowercase variables make that parse back)."""
    if e in labels:
        return labels[e]
    if isinstance(e, Const):
        return ("T" if e.value else "F") if tf else ("1" if e.value else "0")
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Not):
        inner = _discrete(e.arg, tf, labels)
        if isinstance(e.arg, (Var, Const, Not)) or e.arg in labels:
            return "¬" + inner
        return "¬" + _bracket(inner)
    assert isinstance(e, Op)
    parts = []
    for a in e.args:
        s = _discrete(a, tf, labels)
        parts.append(_bracket(s) if isinstance(a, Op) and a not in labels else s)
    return _DSYM[e.kind].join(parts)


def render_labeled(e: Expr, labels: Mapping[Expr, str]) -> str:
    """Discrete style with known sub-expressions replaced by labels: '(1) ∧ ¬q'."""
    return _discrete(e, _has_lower(e), {k: v for k, v in labels.items() if k != e})


def _bracket(s: str) -> str:
    """( ) innermost, then [ ], then { } — the way Rosen writes [(p → q) ∧ p] → q."""
    if "{" in s:
        return f"({s})"
    if "[" in s:
        return f"{{{s}}}"
    if "(" in s:
        return f"[{s}]"
    return f"({s})"


# ---- tokenizer ----------------------------------------------------------------------------

_KEYWORDS = {"not": "not", "and": "and", "or": "or", "xor": "xor", "implies": "imp", "iff": "iff",
             "true": "1", "false": "0"}

_SYMBOLS = sorted({
    "<->": "iff", "<=>": "iff", "↔": "iff", "⇔": "iff", "⟷": "iff", "⟺": "iff",
    "->": "imp", "=>": "imp", "→": "imp", "⇒": "imp", "⟶": "imp", "⟹": "imp",
    "¬": "not", "~": "not", "!": "not",
    "'": "post", "’": "post", "′": "post", "̅": "post", "̄": "post",
    "&&": "and", "∧": "and", "&": "and", "*": "and", "·": "and", "⋅": "and", "∙": "and", ".": "and",
    "||": "or", "∨": "or", "|": "or", "+": "or",
    "⊕": "xor", "⊻": "xor",
    "(": "lp", "[": "lp", "{": "lp", ")": "rp", "]": "rp", "}": "rp",
    "⊤": "1", "⊥": "0",
}.items(), key=lambda kv: -len(kv[0]))
_CLOSE = {"(": ")", "[": "]", "{": "}"}

# "F = ", "Y=", "F(A,B,C) = " before an answer. Only function-like names, so `p = q` stays an error.
_LHS = re.compile(r"\s*[FfGgHhYyZz]\s*(\(\s*[A-Za-z](\s*,\s*[A-Za-z])*\s*\))?\s*=(?![=>])")


@dataclass(frozen=True)
class _Tok:
    kind: str           # var const not post and or xor imp iff lp rp end
    text: str           # as typed
    pos: int
    value: str = ""     # variable name, '0' / '1' for constants

    @property
    def end(self) -> int:
        return self.pos + len(self.text)


def _tokenize(text: str, start: int) -> list[_Tok]:
    toks: list[_Tok] = []
    solo_tf: list[int] = []
    i, n = start, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c.isascii() and c.isalpha():
            j = i
            while j < n and text[j].isascii() and text[j].isalpha():
                j += 1
            word = text[i:j]
            kw = _KEYWORDS.get(word.lower())
            if kw in ("0", "1"):
                toks.append(_Tok("const", word, i, kw))
            elif kw:
                toks.append(_Tok(kw, word, i))
            elif len(word) == 1 or word.isupper():
                if word in ("T", "F"):
                    solo_tf.append(len(toks))
                toks.extend(_Tok("var", ch, i + k, ch) for k, ch in enumerate(word))
            else:
                raise ParseError(_word_message(word), text, i)
            i = j
            continue
        if c in "0123456789":
            j = i
            while j < n and text[j] in "0123456789":
                j += 1
            if text[i:j] not in ("0", "1"):
                raise ParseError(f"{text[i:j]!r} isn't a constant — the constants are 0 and 1", text, i)
            toks.append(_Tok("const", text[i:j], i, text[i:j]))
            i = j
            continue
        for sym, kind in _SYMBOLS:
            if text.startswith(sym, i):
                if kind in ("0", "1"):
                    toks.append(_Tok("const", sym, i, kind))
                else:
                    toks.append(_Tok(kind, sym, i))
                i += len(sym)
                break
        else:
            raise ParseError(_char_message(c), text, i)
    toks.append(_Tok("end", "", n))
    if any(t.kind == "var" and t.value.islower() for t in toks):
        for k in solo_tf:                       # Rosen's T and F next to p, q, r
            t = toks[k]
            toks[k] = _Tok("const", t.text, t.pos, "1" if t.value == "T" else "0")
    return toks


def _word_message(word: str) -> str:
    if re.fullmatch(r"[a-z](v[a-z])+", word):
        return f"unknown word {word!r} — for OR write {' ∨ '.join(word[::2])} (or use |)"
    if len(word) <= 4:
        return (f"unknown word {word!r} — variables are single letters: write {' & '.join(word)} for AND "
                "(adjacency means AND only in uppercase, like AB')")
    return f"unknown word {word!r} — variables are single letters; the word operators are not and or xor implies iff"


def _char_message(c: str) -> str:
    if c == "^":
        return "ambiguous: write & for AND or xor for XOR"
    if c == "=":
        return "unexpected '=' — write -> for implies, <-> for iff"
    if c == "-":
        return "unexpected '-' — write -> for implies"
    if c in "<>":
        return f"unexpected {c!r} — write -> for implies, <-> for iff"
    if c in ",;":
        return f"unexpected {c!r} — one expression at a time"
    return f"unexpected character {c!r}"


# ---- parser -------------------------------------------------------------------------------

def parse(text: str) -> Expr:
    """Parse either notation (see the module docstring). Raises ParseError (a ValueError)."""
    if len(text) > MAX_LEN:
        raise ParseError(f"expression too long (over {MAX_LEN} characters)", text[:60] + "…", 0)
    m = _LHS.match(text)
    return _Parser(text, m.end() if m else 0).parse()


class _Parser:
    def __init__(self, text: str, start: int):
        self.text = text
        self.toks = _tokenize(text, start)
        self.i = 0
        self.depth = 0

    def peek(self) -> _Tok:
        return self.toks[self.i]

    def take(self) -> _Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def prev(self) -> _Tok | None:
        return self.toks[self.i - 1] if self.i else None

    def err(self, message: str, pos: int) -> ParseError:
        return ParseError(message, self.text, pos)

    def enter(self, t: _Tok) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.err("too deeply nested", t.pos)

    def parse(self) -> Expr:
        if self.peek().kind == "end":
            raise self.err("empty expression", self.peek().pos)
        e = self.iff()
        t = self.peek()
        if t.kind != "end":                      # only a closing bracket stops the loops early
            raise self.err(f"unmatched {t.text!r}", t.pos)
        return e

    def iff(self) -> Expr:
        left = self.imp()
        while self.peek().kind == "iff":
            self.take()
            left = IFF(left, self.imp())
        return left

    def imp(self) -> Expr:
        left = self.or_()
        if self.peek().kind != "imp":
            return left
        t = self.take()
        self.enter(t)
        right = self.imp()                       # right-associative: p → q → r = p → (q → r)
        self.depth -= 1
        return IMP(left, right)

    def or_(self) -> Expr:
        parts = [self.xor()]
        while self.peek().kind == "or":
            self.take()
            parts.append(self.xor())
        return OR(*parts)

    def xor(self) -> Expr:
        parts = [self.and_()]
        while self.peek().kind == "xor":
            self.take()
            parts.append(self.and_())
        return XOR(*parts)

    def and_(self) -> Expr:
        start = self.peek().pos
        last = self.unary()
        last_src = self.text[start:self.prev().end]
        parts = [last]
        while True:
            t = self.peek()
            if t.kind == "and":
                self.take()
                start = self.peek().pos
            elif t.kind in ("var", "const", "lp", "not"):
                start = t.pos                     # adjacency
            else:
                break
            right = self.unary()
            src = self.text[start:self.prev().end]
            if t.kind != "and" and (_has_lower(last) or _has_lower(right)):
                raise self.err(_adjacency_message(last_src, src, right), start)
            parts.append(right)
            last, last_src = right, src
        return AND(*parts)

    def unary(self) -> Expr:
        t = self.peek()
        if t.kind == "not":
            self.take()
            self.enter(t)
            e = Not(self.unary())
            self.depth -= 1
            return e
        e = self.atom()
        while self.peek().kind == "post":
            self.take()
            e = Not(e)
        return e

    def atom(self) -> Expr:
        t = self.peek()
        if t.kind == "var":
            self.take()
            return Var(t.value)
        if t.kind == "const":
            self.take()
            return Const(t.value == "1")
        if t.kind == "lp":
            self.take()
            self.enter(t)
            if self.peek().kind == "rp":
                raise self.err("empty brackets", self.peek().pos)
            e = self.iff()
            close = self.peek()
            if close.kind != "rp":
                raise self.err(f"this {t.text!r} is never closed", t.pos)
            if close.text != _CLOSE[t.text]:
                raise self.err(f"{close.text!r} doesn't match the {t.text!r} at column {t.pos + 1}", close.pos)
            self.take()
            self.depth -= 1
            return e
        prev = self.prev()
        if t.kind == "end":
            msg = f"missing operand after {prev.text!r}" if prev else "empty expression"
        elif t.kind == "post":
            msg = f"{t.text!r} (NOT) goes after a variable or a bracket, like A' or (A + B)'"
        elif t.kind == "rp":
            msg = "empty brackets" if prev and prev.kind == "lp" else f"missing operand before {t.text!r}"
        elif prev is None:
            msg = f"{t.text!r} needs something on its left"
        else:
            msg = f"missing operand between {prev.text!r} and {t.text!r}"
        raise self.err(msg, t.pos)


def _adjacency_message(left: str, right: str, right_expr: Expr) -> str:
    if right_expr == Var("v"):
        return "'v' is read as a variable — for OR write ∨, | or 'or'"
    left, right = _short(left), _short(right)
    return (f"missing operator between {left} and {right} — write {left} & {right} for AND "
            "(adjacency means AND only between uppercase letters, like AB')")


def _short(src: str) -> str:
    src = src.strip()
    return src if len(src) <= 12 else src[:11] + "…"


# ---- evaluation ---------------------------------------------------------------------------

def _names(n: int, names: Sequence[str] | str | None) -> list[str]:
    if names is None:
        if n > len(DEFAULT_NAMES):
            raise ValueError(f"at most {len(DEFAULT_NAMES)} variables")
        return list(DEFAULT_NAMES[:n])
    out = list(names)
    if len(out) != n:
        raise ValueError(f"need {n} variable names, got {len(out)}")
    return out


def _check_names(names: Sequence[str]) -> list[str]:
    out = list(names)
    if len(set(out)) != len(out) or not all(len(v) == 1 and v.isascii() and v.isalpha() for v in out):
        raise ValueError(f"variables must be distinct letters, got {''.join(out)!r}")
    if len(out) > MAX_VARS:
        raise ValueError(f"at most {MAX_VARS} variables")
    return out


@functools.lru_cache(maxsize=None)
def _var_mask(i: int, n: int) -> int:
    """Bit m set iff variable i (0 = most significant) is 1 in minterm m."""
    bit = 1 << (n - 1 - i)
    return sum(1 << m for m in range(1 << n) if m & bit)


def truth_mask(expr: Expr, vars: Sequence[str] | str) -> int:
    """The whole truth table as an int: bit m is the value on minterm m (vars[0] is the MSB)."""
    names = _check_names(vars)
    missing = sorted(expr.vars() - set(names))
    if missing:
        raise ValueError(f"the expression uses {', '.join(missing)}, which isn't among {', '.join(names)}")
    n = len(names)
    full = (1 << (1 << n)) - 1
    masks = {v: _var_mask(i, n) for i, v in enumerate(names)}

    def go(e: Expr) -> int:
        if isinstance(e, Const):
            return full if e.value else 0
        if isinstance(e, Var):
            return masks[e.name]
        if isinstance(e, Not):
            return full & ~go(e.arg)
        assert isinstance(e, Op)
        vals = [go(a) for a in e.args]
        if e.kind == "and":
            return functools.reduce(lambda a, b: a & b, vals)
        if e.kind == "or":
            return functools.reduce(lambda a, b: a | b, vals)
        if e.kind == "xor":
            return functools.reduce(lambda a, b: a ^ b, vals)
        if e.kind == "imp":
            return (full & ~vals[0]) | vals[1]
        return full & ~(vals[0] ^ vals[1])          # iff

    return go(expr)


def truth_table(expr: Expr, vars: Sequence[str] | str | None = None) -> list[tuple[tuple[bool, ...], bool]]:
    """[(assignment, value)] in minterm order: all-false first, vars[0] most significant.
    vars defaults to the expression's variables, sorted."""
    names = sorted(expr.vars()) if vars is None else list(vars)
    mask = truth_mask(expr, names)
    n = len(names)
    return [(tuple(bool(m >> (n - 1 - i) & 1) for i in range(n)), bool(mask >> m & 1))
            for m in range(1 << n)]


def minterms(expr: Expr, vars: Sequence[str] | str | None = None) -> list[int]:
    """Minterm numbers where expr is 1 (vars[0] is the most significant bit)."""
    names = sorted(expr.vars()) if vars is None else list(vars)
    mask = truth_mask(expr, names)
    return [m for m in range(1 << len(names)) if mask >> m & 1]


# ---- sums of products ---------------------------------------------------------------------

def _is_literal(e: Expr) -> bool:
    return isinstance(e, Var) or (isinstance(e, Not) and isinstance(e.arg, Var))


def _factors(term: Expr) -> tuple[Expr, ...]:
    return term.args if isinstance(term, Op) and term.kind == "and" else (term,)


def _terms(e: Expr) -> tuple[Expr, ...]:
    return e.args if isinstance(e, Op) and e.kind == "or" else (e,)


def _is_product(e: Expr) -> bool:
    return all(_is_literal(f) or isinstance(f, Const) for f in _factors(e))


def is_sop(expr: Expr) -> bool:
    """A sum of products of literals: AB' + C, A, 1. No brackets, no NOT over a group."""
    return all(_is_product(t) for t in _terms(expr))


def cost(expr: Expr) -> tuple[int, int]:
    """(terms, literals) of a sum of products: AB' + C -> (2, 3); 0 -> (0, 0); 1 -> (1, 0).
    A constant written inside a longer product counts as a literal (A·1 isn't simplified).
    For other expressions: top-level OR operands and variable occurrences."""
    if expr == FALSE:
        return 0, 0
    literals = 0
    for t in _terms(expr):
        fs = _factors(t)
        if is_sop(expr):
            literals += sum(1 for f in fs if _is_literal(f) or len(fs) > 1)
        else:
            literals += _occurrences(t)
    return len(_terms(expr)), literals


def _occurrences(e: Expr) -> int:
    if isinstance(e, Var):
        return 1
    if isinstance(e, Not):
        return _occurrences(e.arg)
    if isinstance(e, Op):
        return sum(_occurrences(a) for a in e.args)
    return 0


def implicants_of(expr: Expr, vars: Sequence[str] | str) -> list[Implicant] | None:
    """The product terms of an SOP as Implicants over `vars` (None if not an SOP, or a term is
    contradictory like AA' or contains a constant 0)."""
    if not is_sop(expr):
        return None
    names = list(vars)
    n = len(names)
    out = []
    for t in _terms(expr):
        if t == FALSE:
            return None
        value, fixed = 0, 0
        for f in _factors(t):
            if isinstance(f, Const):
                if not f.value:
                    return None
                continue
            name = f.name if isinstance(f, Var) else f.arg.name
            bit = 1 << (n - 1 - names.index(name))
            want = bit if isinstance(f, Var) else 0
            if fixed & bit and (value & bit) != want:
                return None
            fixed |= bit
            value |= want
        out.append(Implicant(n, value, ((1 << n) - 1) & ~fixed))
    return out


# ---- implicants and minimisation ----------------------------------------------------------

def _popcount(x: int) -> int:
    return bin(x).count("1")


@dataclass(frozen=True)
class Implicant:
    """A product term, or K-map group, over n variables. Variable i (A = 0) is bit n-1-i of a
    minterm number; `dash` marks the variables the group doesn't depend on, `value` the fixed bits."""
    n: int
    value: int
    dash: int = 0

    @property
    def literals(self) -> int:
        return self.n - _popcount(self.dash)

    @property
    def size(self) -> int:
        return 1 << _popcount(self.dash)

    def covers(self, m: int) -> bool:
        return (m & ~self.dash) == self.value

    def minterms(self) -> list[int]:
        out, sub = [], self.dash
        while True:
            out.append(self.value | sub)
            if sub == 0:
                return sorted(out)
            sub = (sub - 1) & self.dash

    def pattern(self) -> str:
        """'01-1': fixed bits, '-' where the group spans both values (A first)."""
        out = []
        for i in range(self.n):
            bit = 1 << (self.n - 1 - i)
            out.append("-" if self.dash & bit else "1" if self.value & bit else "0")
        return "".join(out)

    def _literals(self, names: Sequence[str]) -> list[tuple[str, bool]]:
        return [(names[i], c == "1") for i, c in enumerate(self.pattern()) if c != "-"]

    def to_str(self, names: Sequence[str] | str | None = None, style: str = "design") -> str:
        """A'BD (design) or ¬p ∧ q (discrete); '1' when the group covers everything."""
        lits = self._literals(_names(self.n, names))
        if not lits:
            return "1"
        if style == "discrete":
            return " ∧ ".join(("" if pos else "¬") + v for v, pos in lits)
        sep = "·" if any(v.islower() for v, _ in lits) else ""
        return sep.join(v + ("" if pos else "'") for v, pos in lits)

    def to_sum_str(self, names: Sequence[str] | str | None = None) -> str:
        """Read as a group of 0s (a maxterm group of the complement): A'B -> A + B'."""
        lits = self._literals(_names(self.n, names))
        if not lits:
            return "0"
        return " + ".join(v + ("'" if pos else "") for v, pos in lits)

    def to_expr(self, names: Sequence[str] | str | None = None) -> Expr:
        lits = self._literals(_names(self.n, names))
        if not lits:
            return TRUE
        return AND(*(Var(v) if pos else Not(Var(v)) for v, pos in lits))

    def __str__(self) -> str:
        return self.to_str()


def sop_str(implicants: Sequence[Implicant], names: Sequence[str] | str | None = None,
            style: str = "design") -> str:
    """'B'D' + BD'; '0' for no terms."""
    if not implicants:
        return "0"
    if style == "discrete":
        parts = [i.to_str(names, "discrete") for i in implicants]
        if len(parts) == 1:
            return parts[0]
        return " ∨ ".join(f"({p})" if " " in p else p for p in parts)
    return " + ".join(i.to_str(names) for i in implicants)


def pos_str(groups: Sequence[Implicant], names: Sequence[str] | str | None = None) -> str:
    """A product of sums from groups of 0s (what minimal_pos returns): '(A + B')(C + D)'; '1' for none."""
    if not groups:
        return "1"
    parts = []
    for g in groups:
        s = g.to_sum_str(names)
        if s == "0":
            return "0"
        parts.append(s if " " not in s else f"({s})")
    lower = any(c.islower() for p in parts for c in p)
    out = parts[0]
    for prev, part in zip(parts, parts[1:]):
        # A(B + C) and (A + B)C read fine; two bare literals need no help either (AB) unless lowercase
        out += ("·" if lower else "") + part
    return out


def _canon(p: Implicant) -> tuple[int, int, int]:
    """Lowest cell first, bigger groups first: the order a student reads a K-map."""
    return p.value, -p.size, p.dash


@dataclass
class Minimization:
    n: int
    on: tuple[int, ...]
    dc: tuple[int, ...]
    primes: list[Implicant]                         # prime implicants covering at least one 1
    essential: list[Implicant]
    why_essential: dict[Implicant, int]             # a 1-cell only that prime covers
    remaining: tuple[int, ...]                      # 1-cells the essential primes leave uncovered
    cover: list[Implicant]                          # the chosen minimal cover
    alternatives: list[list[Implicant]] = field(default_factory=list)   # other covers, same cost

    @property
    def cost(self) -> tuple[int, int]:
        return len(self.cover), sum(p.literals for p in self.cover)


def _validate(n: int, on: Iterable[int], dc: Iterable[int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if not 0 <= n <= MAX_VARS:
        raise ValueError(f"{n} variables: dojo handles 0 to {MAX_VARS}")
    on_t, dc_t = tuple(sorted(set(on))), tuple(sorted(set(dc)))
    top = (1 << n) - 1
    for m in on_t + dc_t:
        if not 0 <= m <= top:
            raise ValueError(f"m{m} is out of range: {n} variables have minterms 0–{top}")
    both = sorted(set(on_t) & set(dc_t))
    if both:
        raise ValueError(f"m{both[0]} is both a minterm and a don't-care")
    return on_t, dc_t


def prime_implicants(n: int, minterms: Iterable[int], dontcares: Iterable[int] = ()) -> list[Implicant]:
    """Quine–McCluskey: merge groups that differ in one variable until nothing merges. Primes that
    cover only don't-cares are dropped (no cover needs them)."""
    on, dc = _validate(n, minterms, dontcares)
    current = {(m, 0) for m in on + dc}
    primes: set[tuple[int, int]] = set()
    while current:
        by_key: dict[tuple[int, int], set[int]] = {}
        for value, dash in current:
            by_key.setdefault((dash, _popcount(value)), set()).add(value)
        merged, used = set(), set()
        for (dash, ones), values in by_key.items():
            upper = by_key.get((dash, ones + 1))
            if not upper:
                continue
            for v in values:
                for i in range(n):
                    bit = 1 << i
                    if not (dash | v) & bit and v | bit in upper:
                        merged.add((v, dash | bit))
                        used.add((v, dash))
                        used.add((v | bit, dash))
        primes |= current - used
        current = merged
    out = [Implicant(n, v, d) for v, d in primes]
    return sorted((p for p in out if any(p.covers(m) for m in on)), key=_canon)


def analyze(n: int, minterms: Iterable[int], dontcares: Iterable[int] = ()) -> Minimization:
    """Everything a worked solution needs: primes, essential primes, the minimal cover (fewest
    terms, then fewest literals) found with Petrick's method, and other covers of equal cost."""
    on, dc = _validate(n, minterms, dontcares)
    primes = prime_implicants(n, on, dc)
    covering = {m: [i for i, p in enumerate(primes) if p.covers(m)] for m in on}
    why: dict[Implicant, int] = {}
    for m in on:
        if len(covering[m]) == 1:
            why.setdefault(primes[covering[m][0]], m)
    essential = sorted(why, key=_canon)
    remaining = tuple(m for m in on if not any(p.covers(m) for p in essential))
    winners = _petrick(primes, remaining, covering)
    covers = [sorted(essential + [primes[i] for i in w], key=_canon) for w in winners]
    return Minimization(n, on, dc, primes, essential, why, remaining, covers[0], covers[1:9])


def minimize(n: int, minterms: Iterable[int], dontcares: Iterable[int] = ()) -> list[Implicant]:
    """A minimal sum of products: fewest terms, then fewest literals; the same answer every time."""
    return analyze(n, minterms, dontcares).cover


def minimal_pos(n: int, minterms: Iterable[int], dontcares: Iterable[int] = ()) -> list[Implicant]:
    """A minimal product of sums, as groups of 0s: the minimal SOP of the complement (render with
    pos_str or Implicant.to_sum_str)."""
    on, dc = _validate(n, minterms, dontcares)
    zeros = [m for m in range(1 << n) if m not in set(on) | set(dc)]
    return minimize(n, zeros, dc)


def _petrick(primes: list[Implicant], remaining: Sequence[int],
             covering: Mapping[int, list[int]]) -> list[tuple[int, ...]]:
    """All cheapest ways to cover `remaining` (each a tuple of prime indices), best first.

    Petrick's method: the cover condition is a product of sums (one sum of primes per cell),
    multiplied out with absorption (X + XY = X). Products that already cost more than a greedy
    cover are dropped as they appear — cost only grows — so the result stays exact."""
    if not remaining:
        return [()]
    lit = [p.literals for p in primes]

    def cost(prod: int) -> tuple[int, int]:
        return _popcount(prod), sum(lit[i] for i in _bits(prod))

    clauses = sorted({sum(1 << i for i in covering[m]) for m in remaining}, key=lambda c: (_popcount(c), c))
    reduced: list[int] = []
    for c in clauses:                       # (a)(a + b) = (a): a clause containing another is implied
        if not any(r & c == r for r in reduced):
            reduced.append(c)
    bound = cost(_greedy(primes, remaining, covering))
    products = {0}
    for c in reduced:
        grown = set()
        for prod in products:
            if prod & c:
                grown.add(prod)
                continue
            for i in _bits(c):
                q = prod | 1 << i
                if cost(q) <= bound:
                    grown.add(q)
        products = _absorb(grown)
    best = min(cost(p) for p in products)
    return sorted((tuple(_bits(p)) for p in products if cost(p) == best))


def _greedy(primes: list[Implicant], remaining: Sequence[int], covering: Mapping[int, list[int]]) -> int:
    left = set(remaining)
    chosen = 0
    while left:
        cands = {i for m in left for i in covering[m]}
        best = max(sorted(cands), key=lambda i: (sum(1 for m in left if primes[i].covers(m)), -primes[i].literals))
        chosen |= 1 << best
        left = {m for m in left if not primes[best].covers(m)}
    return chosen


def _absorb(products: set[int]) -> set[int]:
    kept: list[int] = []
    for p in sorted(products, key=lambda x: (_popcount(x), x)):
        if not any(k & p == k for k in kept):
            kept.append(p)
    return set(kept)


def _bits(x: int) -> list[int]:
    out, i = [], 0
    while x:
        if x & 1:
            out.append(i)
        x >>= 1
        i += 1
    return out
