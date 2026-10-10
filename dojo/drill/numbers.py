"""Number drills for CIS 203 Logic Design: number bases and signed binary.

    base   convert between bases 2, 8, 10 and 16 (level 3: fixed-point fractions)
    twos   n-bit two's complement: encode, decode, add/subtract, overflow, range
           (level 3 adds sign-magnitude and one's complement)

Answers are computed exactly (int, Fraction). The worked solutions are the paper methods:
repeated division with a remainder column, positional expansion, 3-/4-bit grouping,
invert-and-add-1, and column addition with the carry row and the overflow rule.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable

from dojo.drill.core import Question, Topic, Verdict, norm, register

DIGITS = "0123456789ABCDEF"
NAMES = {2: "binary", 8: "octal", 10: "decimal", 16: "hexadecimal"}
_WORDS = {"bin": 2, "binary": 2, "oct": 8, "octal": 8, "dec": 10, "decimal": 10,
          "hex": 16, "hexadecimal": 16}
_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_DASHES = str.maketrans({"−": "-", "–": "-", "—": "-"})


def base_name(base: int) -> str:
    return NAMES.get(base, f"base-{base}")


def _sup(k: int) -> str:
    return str(k).translate(_SUP)


# ---- base conversion ---------------------------------------------------------------------------

def int_digits(n: int, base: int) -> str:
    """A non-negative integer written in `base` (2–16), upper-case digits."""
    if n < 0:
        raise ValueError("negative")
    out = []
    while True:
        n, r = divmod(n, base)
        out.append(DIGITS[r])
        if not n:
            return "".join(reversed(out))


@dataclass(frozen=True)
class Expansion:
    """A non-negative value written in some base. When the fraction never terminates, `cycle`
    is the block that repeats forever after `frac` (or `cut` says we gave up looking)."""
    whole: str
    frac: str = ""
    cycle: str = ""
    cut: bool = False

    @property
    def exact(self) -> bool:
        return not self.cycle and not self.cut

    def __str__(self) -> str:
        if self.cycle:
            return f"{self.whole}.{self.frac}({self.cycle})"
        if self.cut:
            return f"{self.whole}.{self.frac}…"
        return f"{self.whole}.{self.frac}" if self.frac else self.whole

    def digits(self, k: int) -> str:
        """The first k fraction digits (repeating the cycle as needed)."""
        out = self.frac
        while self.cycle and len(out) < k:
            out += self.cycle
        return out[:k]


def expand(value: Fraction | int, base: int, max_frac: int = 48) -> Expansion:
    v = Fraction(value)
    if v < 0:
        raise ValueError("negative")
    whole = v.numerator // v.denominator
    rest = v - whole
    digits: list[str] = []
    seen: dict[Fraction, int] = {}
    while rest:
        if rest in seen:
            i = seen[rest]
            return Expansion(int_digits(whole, base), "".join(digits[:i]), "".join(digits[i:]))
        if len(digits) >= max_frac:
            return Expansion(int_digits(whole, base), "".join(digits), cut=True)
        seen[rest] = len(digits)
        rest *= base
        d = rest.numerator // rest.denominator
        digits.append(DIGITS[d])
        rest -= d
    return Expansion(int_digits(whole, base), "".join(digits))


def to_base(value: Fraction | int, base: int) -> str:
    """'1010.101' for (85/8, 2). Non-terminating fractions show the repeating block in ()."""
    return str(expand(value, base))


def value_of(digits: str, base: int) -> Fraction:
    """'1010.101' in base 2 -> 85/8 (case-insensitive). ValueError names the first bad digit."""
    t = digits.strip().upper()
    whole, _, frac = t.partition(".")
    if not t or t == "." or "." in frac:
        raise ValueError(f"{digits.strip()!r} isn't a number")
    v = Fraction(0)
    for ch in whole:
        v = v * base + _digit(ch, base)
    scale = Fraction(1)
    for ch in frac:
        scale /= base
        v += _digit(ch, base) * scale
    return v


def _digit(ch: str, base: int) -> int:
    d = DIGITS.find(ch)
    if d < 0 or d >= base:
        raise ValueError(f"{ch!r} isn't a {base_name(base)} digit")
    return d


_PREFIXES = {"0X": 16, "0B": 2, "0O": 8}


def _split_marker(t: str) -> tuple[str, int | None]:
    """'(2D)16', '2D(16)', '2D₁₆' -> ('2D', 16). Anything else -> (t, None)."""
    m = re.fullmatch(r"\((.+)\)([0-9₀-₉]+)", t)
    if not m:
        m = re.fullmatch(r"(.+?)(?:\((\d+)\)|([₀-₉]+))", t)
        if not m:
            return t, None
        return m.group(1), int((m.group(2) or m.group(3)).translate(_SUB))
    return m.group(1), int(m.group(2).translate(_SUB))


def read_numeral(text: str, base: int) -> tuple[Fraction, str]:
    """A typed answer in `base` -> (value, upper-case digits). Spaces and underscores are ignored,
    and so are a matching 0x/0b/0o prefix and a base mark like 2D₁₆, (2D)16 or 2D(16)."""
    t = text.strip().translate(_DASHES).replace(" ", "").replace("_", "")
    t, marked = _split_marker(t)
    if marked is not None and marked != base:
        raise ValueError(f"that's marked base {marked}; the question asks for {base_name(base)}")
    up = t.upper()
    if len(up) > 2 and up[:2] in _PREFIXES:
        b = _PREFIXES[up[:2]]
        if b == base:
            up = up[2:]
        elif not (base == 16 and b == 2):          # 0B6D is a hex number with a leading zero
            raise ValueError(f"{up[:2].lower()} means {base_name(b)}; write the answer in {base_name(base)}")
    if base == 10 and "/" in up:
        raise ValueError("write it with a decimal point, not as a fraction")
    return value_of(up, base), up


# ---- worked steps for base conversion -----------------------------------------------------------

def _dec(q: Fraction) -> str:
    """Exact decimal for terminating values (all the generated ones), else 6 places with '…'."""
    e = expand(abs(q), 10, max_frac=6)
    s = f"{e.whole}.{e.digits(6)}…" if not e.exact else str(e)
    return ("-" if q < 0 else "") + s


def _division_lines(n: int, base: int) -> list[str]:
    rows = []
    while True:
        q, r = divmod(n, base)
        rows.append((n, q, r))
        n = q
        if not n:
            break
    wn, wq = len(str(rows[0][0])), len(str(rows[0][1]))
    out = []
    for i, (a, q, r) in enumerate(rows):
        digit = f" = {DIGITS[r]}" if r >= 10 else ""
        tag = "   (rightmost digit)" if i == 0 and len(rows) > 1 else "   (leftmost digit)" if i == len(rows) - 1 and len(rows) > 1 else ""
        out.append(f"  {a:>{wn}} ÷ {base} = {q:>{wq}}   remainder {r:>2}{digit}{tag}")
    return out


def _multiplication_lines(frac: Fraction, base: int, limit: int = 12) -> tuple[list[str], bool]:
    """Repeated multiplication of the fraction part; returns (lines, terminated)."""
    rows, seen = [], set()
    while frac and len(rows) < limit and frac not in seen:
        seen.add(frac)
        p = frac * base
        d = p.numerator // p.denominator
        rows.append((_dec(frac), _dec(p), d))
        frac = p - d
    w1 = max(len(r[0]) for r in rows)
    w2 = max(len(r[1]) for r in rows)
    out = []
    for a, p, d in rows:
        digit = f" = {DIGITS[d]}" if d >= 10 else ""
        out.append(f"  {a:<{w1}} × {base} = {p:<{w2}}   integer part {d}{digit}")
    return out, frac == 0


def _place_value_lines(whole: str, frac: str, base: int) -> list[str]:
    """Positional expansion: digit × base^position, summed."""
    terms = []                                   # (digit value, power, digit char)
    for i, ch in enumerate(whole):
        terms.append((DIGITS.index(ch), len(whole) - 1 - i, ch))
    for i, ch in enumerate(frac):
        terms.append((DIGITS.index(ch), -(i + 1), ch))
    nonzero = [t for t in terms if t[0]]
    if not nonzero:
        return ["  = 0"]
    out = []
    letters = sorted({ch for d, _, ch in nonzero if d >= 10})
    if letters:
        out.append("  digits: " + ", ".join(f"{ch} = {DIGITS.index(ch)}" for ch in letters))
    shown = terms if base == 2 and len(terms) <= 8 else nonzero
    if base == 2 and len(terms) > 8:
        out.append("  " + " + ".join(f"2{_sup(p)}" for _, p, _ in shown) + "   (the 1 bits)")
    else:
        out.append("  " + " + ".join(f"{d}×{base}{_sup(p)}" for d, p, _ in shown))
    values = [d * Fraction(base) ** p for d, p, _ in nonzero]
    if len(values) > 1:
        out.append("  = " + " + ".join(_dec(v) for v in values))
    out.append(f"  = {_dec(sum(values))}")
    return out


def _group_lines(whole: str, frac: str, size: int) -> tuple[list[str], str]:
    """Bits grouped from the point outward (pad the integer part on the left, the fraction on the
    right); one digit per group. Returns (two aligned lines, the digits)."""
    w = whole.lstrip("0") or "0"
    w = "0" * (-len(w) % size) + w
    f = frac + "0" * (-len(frac) % size)
    gw = [w[i:i + size] for i in range(0, len(w), size)]
    gf = [f[i:i + size] for i in range(0, len(f), size)]
    dw = [DIGITS[int(g, 2)] for g in gw]
    df = [DIGITS[int(g, 2)] for g in gf]
    top = " ".join(gw) + (" . " + " ".join(gf) if gf else "")
    bottom = " ".join(d.rjust(size) for d in dw) + (" . " + " ".join(d.rjust(size) for d in df) if df else "")
    digits = "".join(dw).lstrip("0") or "0"
    if df:
        digits += "." + "".join(df).rstrip("0")
        digits = digits.rstrip(".")
    return ["  " + top, "  " + bottom], digits


def _expand_lines(whole: str, frac: str, size: int) -> tuple[list[str], str, str]:
    """Each digit written as `size` bits. Returns (two aligned lines, integer bits, fraction bits)."""
    bw = [format(DIGITS.index(ch), f"0{size}b") for ch in whole]
    bf = [format(DIGITS.index(ch), f"0{size}b") for ch in frac]
    top = " ".join(ch.rjust(size) for ch in whole) + (" . " + " ".join(ch.rjust(size) for ch in frac) if frac else "")
    bottom = " ".join(bw) + (" . " + " ".join(bf) if bf else "")
    return ["  " + top, "  " + bottom], "".join(bw).lstrip("0") or "0", "".join(bf).rstrip("0")


_POW2 = {2: 1, 4: 2, 8: 3, 16: 4}


def explain_conversion(value: Fraction, src: int, dst: int) -> list[str]:
    """The paper method for converting `value` from base src to base dst."""
    s = expand(value, src)
    whole, frac = s.whole, s.frac
    if src == dst:
        return [f"Same base: {s}"]
    if src in _POW2 and dst in _POW2 and s.exact:
        if src == 2:
            k = _POW2[dst]
            lines, digits = _group_lines(whole, frac, k)
            how = "from the right" if not frac else "outward from the point (pad the ends with 0s)"
            return [f"Group the bits in {k}s {how}; each group is one {base_name(dst)} digit:",
                    *lines, f"Answer: {digits}"]
        k = _POW2[src]
        lines, bw, bf = _expand_lines(whole, frac, k)
        bits = bw + ("." + bf if bf else "")
        if dst == 2:
            return [f"Write each {base_name(src)} digit as exactly {k} bits:", *lines,
                    f"Drop the leading 0s{' and trailing 0s' if frac else ''}: {bits}"]
        k2 = _POW2[dst]
        glines, digits = _group_lines(bw, bf, k2)
        return [f"Go through binary. Each {base_name(src)} digit as {k} bits:", *lines,
                f"Regroup the bits in {k2}s; each group is one {base_name(dst)} digit:", *glines,
                f"Answer: {digits}"]
    if dst == 10:
        return [f"Multiply each digit by its place value (powers of {src}) and add:",
                *_place_value_lines(whole, frac, src)]
    if src == 10:
        return _from_decimal_lines(value, dst)
    # Any other pair: through decimal.
    return [f"Go through decimal. Place values (powers of {src}):", *_place_value_lines(whole, frac, src),
            *_from_decimal_lines(value, dst)]


def _from_decimal_lines(value: Fraction, dst: int) -> list[str]:
    whole = value.numerator // value.denominator
    frac = value - whole
    t = expand(value, dst)
    lines = []
    if frac:
        lines.append(f"Integer part {whole}: divide by {dst} repeatedly; the remainders are the digits, "
                     "last one first.")
    else:
        lines.append(f"Divide by {dst} repeatedly; the remainders are the digits, last one first.")
    lines += _division_lines(whole, dst)
    lines.append(f"Read the remainders bottom-up: {t.whole}")
    if frac:
        lines.append(f"Fraction part {_dec(frac)}: multiply by {dst} repeatedly; the integer parts are the "
                     "digits, first one first.")
        mlines, done = _multiplication_lines(frac, dst)
        lines += mlines
        if done:
            lines.append(f"The fraction reached 0. Read the integer parts top-down: .{t.frac}")
        elif t.cycle:
            lines.append(f"The fraction repeats: {t.whole}.{t.frac}({t.cycle}) means {t.cycle} repeats forever.")
        else:
            lines.append("The fraction never terminates; stop at the precision you need.")
        lines.append(f"Answer: {t}")
    return lines


def _conversion_hint(src: int, dst: int, fractional: bool) -> str:
    if src == 2 and dst in (8, 16):
        k = _POW2[dst]
        return f"Group the bits in {k}s starting at the binary point; each group is one {base_name(dst)} digit."
    if dst == 2 and src in (8, 16):
        return f"Write each {base_name(src)} digit as exactly {_POW2[src]} bits."
    if {src, dst} == {8, 16}:
        return "Go through binary: 3 bits per octal digit, 4 bits per hex digit."
    if dst == 10:
        return f"Multiply each digit by its place value (a power of {src}) and add."
    hint = f"Divide by {dst} repeatedly; the remainders read bottom-up are the digits."
    if fractional:
        hint += f" For the fraction, multiply by {dst} and keep the integer parts, top-down."
    return hint


def _base_check(value: Fraction, dst: int, src: int) -> Callable[[str], Verdict]:
    want = expand(value, dst)
    size = _POW2.get(dst) if src == 2 else None

    def check(text: str) -> Verdict:
        try:
            got, digits = read_numeral(text, dst)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        if got == value:
            return Verdict(True)
        whole, _, frac = digits.partition(".")
        whole_ok = (whole.lstrip("0") or "0") == want.whole
        if src == 10 and dst != 10:
            if not whole_ok and len(want.whole) > 1 and (whole[::-1].lstrip("0") or "0") == want.whole:
                return Verdict(False, "you read the remainders top-down; the last remainder is the leftmost digit")
            if whole_ok and frac and frac.rstrip("0")[::-1] == want.frac and frac.rstrip("0") != want.frac:
                return Verdict(False, "the fraction digits come out in order: the first product gives the "
                                      "first digit after the point")
        if size and not whole_ok and want.exact:
            bits = expand(value, 2).whole
            wrong = bits + "0" * (-len(bits) % size)          # grouped from the left
            alt = int_digits(int(wrong, 2), dst)
            if alt != want.whole and (whole.lstrip("0") or "0") == alt:
                return Verdict(False, "group the integer bits from the right (pad the left with 0s)")
        return Verdict(False)
    return check


# ---- signed binary ------------------------------------------------------------------------------

def bits_of(u: int, n: int) -> str:
    """The n-bit pattern of a non-negative integer below 2^n."""
    if not 0 <= u < 1 << n:
        raise ValueError(f"{u} doesn't fit in {n} bits")
    return "".join("1" if u >> i & 1 else "0" for i in reversed(range(n)))


def invert(bits: str) -> str:
    return "".join("1" if b == "0" else "0" for b in bits)


def tc_range(n: int) -> tuple[int, int]:
    return -(1 << (n - 1)), (1 << (n - 1)) - 1


def tc_encode(v: int, n: int) -> str:
    lo, hi = tc_range(n)
    if not lo <= v <= hi:
        raise ValueError(f"{v} doesn't fit in {n}-bit two's complement ({lo} … {hi})")
    return bits_of(v + (1 << n) if v < 0 else v, n)


def tc_decode(bits: str) -> int:
    u = int(bits, 2)
    return u - (1 << len(bits)) if bits[0] == "1" else u


def sm_encode(v: int, n: int) -> str:
    m = abs(v)
    if m >= 1 << (n - 1):
        raise ValueError(f"{v} doesn't fit in {n}-bit sign-magnitude")
    return ("1" if v < 0 else "0") + bits_of(m, n - 1)


def sm_decode(bits: str) -> int:
    m = int(bits[1:], 2)
    return -m if bits[0] == "1" else m


def ones_encode(v: int, n: int) -> str:
    if abs(v) >= 1 << (n - 1):
        raise ValueError(f"{v} doesn't fit in {n}-bit one's complement")
    p = bits_of(abs(v), n)
    return invert(p) if v < 0 else p


def ones_decode(bits: str) -> int:
    return -int(invert(bits), 2) if bits[0] == "1" else int(bits, 2)


def ripple_add(a: str, b: str, carry_in: int = 0) -> tuple[str, list[int]]:
    """Column addition of two n-bit patterns. carries[i] is the carry INTO bit i (bit 0 = the
    rightmost), so carries[0] = carry_in and carries[n] is the carry out of the MSB."""
    n = len(a)
    carries = [carry_in] + [0] * n
    out = []
    for i in range(n):
        t = int(a[n - 1 - i]) + int(b[n - 1 - i]) + carries[i]
        out.append("1" if t & 1 else "0")
        carries[i + 1] = t >> 1
    return "".join(reversed(out)), carries


def group(bits: str) -> str:
    """Nibbles from the right for patterns longer than 8 bits: 10 1101 0110."""
    if len(bits) <= 8:
        return bits
    head = len(bits) % 4
    parts = ([bits[:head]] if head else []) + [bits[i:i + 4] for i in range(head, len(bits), 4)]
    return " ".join(parts)


def _article(n: int) -> str:
    return "an" if str(n).startswith("8") or n in (11, 18) else "a"


def addition_table(top: str, bottom: str, carry_in: int = 0, labels: tuple[str, str] = ("", ""),
                   notes: tuple[str, str] = ("", ""), result_note: str = "") -> tuple[list[str], str, list[int]]:
    """Column addition as written on paper. The carry row holds the carry into each column (the
    rightmost is the carry-in) plus, one column further left, the carry out of the MSB."""
    total, c = ripple_add(top, bottom, carry_in)
    n = len(top)
    carry_row = str(c[n]) + group("".join(str(c[i]) for i in reversed(range(n))))
    w = max(5, len(labels[0]), len(labels[1]))

    def row(label: str, sign: str, bits: str, note: str) -> str:
        return f"  {label:<{w}}  {sign} {bits}" + (f"   {note}" if note else "")

    lines = [f"  {'carry':<{w}}   {carry_row}",          # the carry out sits just left of the MSB
             row(labels[0], " ", group(top), notes[0]),
             row(labels[1], "+", group(bottom), notes[1]),
             row("", " ", "-" * len(group(top)), ""),
             row("", " ", group(total), result_note)]
    return lines, total, c


def _powers(m: int) -> str:
    """45 -> '32 + 8 + 4 + 1'."""
    parts = [str(1 << i) for i in reversed(range(m.bit_length())) if m >> i & 1]
    return " + ".join(parts) if parts else "0"


def _weights(bits: str) -> str:
    """'11010011' -> '-128 + 64 + 16 + 2 + 1 = -45' (the MSB weighs -2^(n-1))."""
    n = len(bits)
    terms = []
    for i, b in enumerate(bits):
        if b == "1":
            w = 1 << (n - 1 - i)
            terms.append(str(-w) if i == 0 else str(w))
    return (" + ".join(terms) if terms else "0") + f" = {tc_decode(bits)}"


def _encode_lines(v: int, n: int) -> list[str]:
    p = tc_encode(v, n)
    if v >= 0:
        return [f"{v} is not negative, so just write it in binary with {n} bits:",
                f"{v} = {_powers(v)} → {group(p)}"]
    m = -v
    if m == 1 << (n - 1):
        first = [f"{v} is the most negative {n}-bit value. +{m} doesn't fit in {n}-bit two's complement,",
                 f"but its {n}-bit unsigned pattern does: {m} = {group(bits_of(m, n))}"]
    else:
        first = [f"Start from +{m} in {n} bits: {m} = {_powers(m)} → {group(bits_of(m, n))}"]
    inv = invert(bits_of(m, n))
    table, total, _ = addition_table(inv, bits_of(1, n))
    return [*first, f"Invert every bit: {group(inv)}", "Add 1:", *table,
            f"{v} = {group(total)}",
            f"Check: the MSB is worth -{1 << (n - 1)}, so {_weights(total)}"]


def _decode_lines(bits: str) -> list[str]:
    n = len(bits)
    v = tc_decode(bits)
    if bits[0] == "0":
        return [f"The MSB is 0, so the value is positive: {group(bits)} = {_powers(v)} = {v}"]
    inv = invert(bits)
    table, total, _ = addition_table(inv, bits_of(1, n))
    m = int(total, 2) if total != "0" * n else 1 << n
    return ["The MSB is 1, so the value is negative. Invert and add 1 to get its size:",
            f"Invert every bit: {group(inv)}", "Add 1:", *table,
            f"{group(total)} = {_powers(m)} = {m}, so the value is -{m}",
            f"Check: the MSB is worth -{1 << (n - 1)}, so {_weights(bits)}"]


def _encode_brief(v: int, n: int) -> str:
    p = tc_encode(v, n)
    if v >= 0:
        return f"{v} = {group(p)}"
    if -v == 1 << (n - 1):
        return f"{v} = {group(p)} (the most negative {n}-bit value)"
    return f"{v}: +{-v} = {group(bits_of(-v, n))}, invert → {group(invert(bits_of(-v, n)))}, add 1 → {group(p)}"


@dataclass
class Arith:
    """A ± B in n-bit two's complement, with everything the solution shows."""
    a: int
    b: int
    op: str                  # "+" or "-"
    n: int
    result: str              # n-bit pattern
    overflow: bool           # from the carry rule
    carry_msb: int           # carry into the MSB
    carry_out: int           # carry out of the MSB
    lines: list[str]

    @property
    def true_value(self) -> int:
        return self.a + self.b if self.op == "+" else self.a - self.b


def arith(a: int, b: int, op: str, n: int, *, given_as_bits: bool = False) -> Arith:
    A, B = tc_encode(a, n), tc_encode(b, n)
    lo, hi = tc_range(n)
    lines: list[str] = []
    if given_as_bits:
        lines.append(f"A = {group(A)} = {a},  B = {group(B)} = {b}")
    else:
        lines += [f"Write both in {n}-bit two's complement:",
                  f"  A = {_encode_brief(a, n)}", f"  B = {_encode_brief(b, n)}"]
    if op == "+":
        lines.append("Add column by column:")
        table, total, c = addition_table(A, B, 0, ("A", "B"), (f"({a})", f"({b})"))
    elif b == lo:
        lines += [f"A - B = A + (two's complement of B). But B = {b} = {group(B)} is the edge case:",
                  f"inverting and adding 1 gives {group(B)} again, because +{-b} doesn't fit in {n} bits.",
                  "So add B inverted (B') and feed the +1 in as the carry into the rightmost column,",
                  "all in one addition:"]
        table, total, c = addition_table(A, invert(B), 1, ("A", "B'"), (f"({a})", "(B inverted)"))
    else:
        negb = tc_encode(-b, n)
        lines += ["A - B = A + (two's complement of B).",
                  f"Two's complement of B: invert {group(B)} → {group(invert(B))}, add 1 → {group(negb)} "
                  f"(= {-b})",
                  "Add column by column:"]
        table, total, c = addition_table(A, negb, 0, ("A", "-B"), (f"({a})", f"({-b})"))
    true = a + b if op == "+" else a - b
    shown = tc_decode(total)
    lines += table
    cin, cout = c[n - 1], c[n]
    overflow = cin != cout
    lines.append(f"Keep {n} bits: {group(total)}" + (f" (the carry out {cout} is dropped)" if cout else ""))
    if overflow:
        lines += [f"Carry into the MSB = {cin}, carry out of the MSB = {cout}: different, so it overflows.",
                  f"Check: {a} {op} {_paren(b)} = {true} is outside {lo} … {hi}; the {n}-bit result "
                  f"{group(total)} reads as {shown}."]
    else:
        lines += [f"Carry into the MSB = {cin}, carry out of the MSB = {cout}: equal, so no overflow.",
                  f"Check: {group(total)} = {shown}, and {a} {op} {_paren(b)} = {true} is inside {lo} … {hi}."]
        if cout:
            lines.append("A carry out of the MSB on its own is not overflow in two's complement.")
    return Arith(a, b, op, n, total, overflow, cin, cout, lines)


def _paren(v: int) -> str:
    return f"({v})" if v < 0 else str(v)


# ---- answer readers ------------------------------------------------------------------------------

def read_bits(text: str, n: int) -> str:
    t = text.strip().translate(_DASHES).replace(" ", "").replace("_", "")
    if t[:2].lower() == "0b":
        t = t[2:]
    if not t:
        raise ValueError(f"type the {n} bits")
    if set(t) - {"0", "1"}:
        if re.fullmatch(r"[+-]?\d+", t):
            raise ValueError(f"write the {n}-bit pattern (0s and 1s), not a decimal number")
        raise ValueError("use only 0 and 1")
    if len(t) != n:
        raise ValueError(f"that's {len(t)} bits; write all {n}")
    return t


def read_int(text: str) -> int:
    t = text.strip().translate(_DASHES).replace(" ", "").replace(",", "")
    m = re.fullmatch(r"([+-]?\d+)(?:\.0*)?", t)
    if not m:
        raise ValueError("write a whole decimal number, like -42")
    return int(m.group(1))


_YES = {"y", "yes", "overflow", "overflows", "true", "it overflows"}
_NO = {"n", "no", "none", "false", "no overflow", "does not overflow", "doesn't overflow"}


def read_yes_no(text: str) -> bool:
    t = norm(text).strip(".!")
    if t in _YES or t.startswith("yes"):
        return True
    if t in _NO or t.startswith("no"):
        return False
    raise ValueError("answer yes or no")


def _bits_check(want: str, slips: dict[str, str] | None = None) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        try:
            got = read_bits(text, len(want))
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        if got == want:
            return Verdict(True)
        return Verdict(False, (slips or {}).get(got, ""))
    return check


def _int_check(want: int, slips: dict[int, str] | None = None) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        try:
            got = read_int(text)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        if got == want:
            return Verdict(True)
        return Verdict(False, (slips or {}).get(got, ""))
    return check


def _yes_no_check(want: bool) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        try:
            got = read_yes_no(text)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        return Verdict(got == want)
    return check


def _range_check(lo: int, hi: int, slips: dict[tuple[int, int], str]) -> Callable[[str], Verdict]:
    def check(text: str) -> Verdict:
        nums = re.findall(r"[+-]?\d+", text.translate(_DASHES))
        if len(nums) != 2:
            return Verdict(False, "give two numbers: the smallest and the largest, like -8 7", retry=True)
        got = tuple(sorted(int(x) for x in nums))
        if got == (lo, hi):
            return Verdict(True)
        if got in slips:
            return Verdict(False, slips[got])
        if got[0] == lo:
            return Verdict(False, "the smallest is right; check the largest")
        if got[1] == hi:
            return Verdict(False, "the largest is right; check the smallest")
        return Verdict(False)
    return check


def _arith_check(want: Arith) -> Callable[[str], Verdict]:
    """The n-bit result; an optional trailing yes/no about overflow is graded too."""
    def check(text: str) -> Verdict:
        claim = None
        m = re.search(r"[\s,;(]*\b(yes|y|no|n)?[\s,]*(?:(no|doesn'?t|does not)\s+)?(overflows?)?\)?\s*$",
                      text.strip(), re.I)
        bits = text
        if m and (m.group(1) or m.group(3)):
            neg = (m.group(1) or "").lower() in ("no", "n") or bool(m.group(2))
            claim = not neg
            bits = text.strip()[:m.start()]
        try:
            got = read_bits(bits, want.n)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        if got != want.result:
            slips = {}
            if want.op == "-":
                A, B = tc_encode(want.a, want.n), tc_encode(want.b, want.n)
                slips[ripple_add(A, B)[0]] = "that's A + B; subtract by adding the two's complement of B"
                slips[ripple_add(A, invert(B))[0]] = "you inverted B but didn't add 1"
            slips.pop(want.result, None)
            return Verdict(False, slips.get(got, ""))
        if claim is not None and claim != want.overflow:
            return Verdict(False, "the bits are right, but " + ("it does overflow" if want.overflow
                                                                 else "it doesn't overflow"))
        return Verdict(True)
    return check


# ---- topics ----------------------------------------------------------------------------------------

_L2_PAIRS = [(10, 2), (2, 10), (10, 16), (16, 10), (2, 16), (16, 2), (10, 8), (8, 10), (2, 8), (8, 2),
             (16, 8), (8, 16)]


@register
class BaseConversion(Topic):
    key, title, course = "base", "Number bases", "CIS 203"
    summary = "convert between bases 2, 8, 10 and 16 (level 3: fractions)"
    solve_usage = "255 to 16 · 0x1F to 2 · 101.101 b2 to 10"

    def generate(self, rng: random.Random, level: int) -> Question:
        if level <= 1:
            src, dst = rng.choice([(10, 2), (2, 10)])
            value = Fraction(rng.randint(10, 100))
        elif level == 2:
            src, dst = rng.choice(_L2_PAIRS)
            value = Fraction(rng.randint(64, 4095))
        else:
            src, dst, value = self._fraction_case(rng)
        return self._question(value, src, dst)

    @staticmethod
    def _fraction_case(rng: random.Random) -> tuple[int, int, Fraction]:
        route = rng.choices(["d2b", "b2d", "b2h", "h2b", "b2o", "o2b", "d2h", "h2d"],
                            [3, 3, 1, 1, 1, 1, 1, 1])[0]
        if route in ("d2b", "b2d"):
            f = rng.randint(2, 4)
            value = rng.randint(1, 63) + Fraction(rng.randrange(1, 1 << f, 2), 1 << f)
        elif route in ("b2h", "h2b", "b2o", "o2b"):
            f = rng.randint(2, 6)
            value = rng.randint(8, 255) + Fraction(rng.randrange(1, 1 << f, 2), 1 << f)
        else:
            value = rng.randint(16, 400) + Fraction(rng.randint(1, 15), 16)
        src, dst = {"d2b": (10, 2), "b2d": (2, 10), "b2h": (2, 16), "h2b": (16, 2), "b2o": (2, 8),
                    "o2b": (8, 2), "d2h": (10, 16), "h2d": (16, 10)}[route]
        return src, dst, value

    def _question(self, value: Fraction, src: int, dst: int, given: str | None = None) -> Question:
        shown = given or to_base(value, src)
        want = expand(value, dst)
        lines = explain_conversion(value, src, dst)
        if dst != 10 and src != 10 and want.exact:
            lines.append(f"Check: both are {_dec(value)} in decimal.")
        return Question(
            prompt=f"Convert the {base_name(src)} number {shown} to {base_name(dst)}.",
            expect="hex" if dst == 16 else base_name(dst),
            check=_base_check(value, dst, src),
            answer=str(want),
            solution="\n".join(lines),
            hint=_conversion_hint(src, dst, value.denominator != 1),
        )

    def solve(self, text: str) -> Question:
        t = text.strip().translate(_DASHES)
        parts = re.split(r"\s+(?:to|in|into)\s+|\s*(?:->|→|=>)\s*", t, maxsplit=1, flags=re.I)
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("say which base to convert to, e.g. 255 to 16")
        left, right = parts[0].split(), parts[1]
        if not left:
            raise ValueError("no number to convert")
        num, src_words = left[0], " ".join(left[1:])
        dst = _base_spec(right)
        src = _base_spec(src_words) if src_words.strip() else None
        num = num.replace("_", "")
        if num.startswith(("-", "+")):
            raise ValueError("this converts non-negative numbers; for signed binary use `dojo solve twos`")
        digits, marked = _split_marker(num)
        if marked is not None:
            if src is not None and src != marked:
                raise ValueError(f"{num} is marked base {marked} but you said base {src}")
            src = marked
        up = digits.upper()
        if len(up) > 2 and up[:2] in _PREFIXES:
            b = _PREFIXES[up[:2]]
            if src is not None and src != b:
                raise ValueError(f"{num} has a {base_name(b)} prefix but you said base {src}")
            src, up = b, up[2:]
        if src is None:
            src = 10
        if not 2 <= src <= 16 or not 2 <= dst <= 16:
            raise ValueError("bases 2 to 16 only")
        if src == dst:
            raise ValueError(f"{num} is already {base_name(src)}")
        try:
            value = value_of(up, src)
        except ValueError as e:
            if src == 10 and re.fullmatch(r"[0-9A-F.]+", up):
                raise ValueError(f"{e} — for hex write 0x{up} or {up} b16") from None
            raise
        q = self._question(value, src, dst, given=up)
        want = expand(value, dst)
        if not want.exact:
            q.check = _repeating_check(value, dst, want)
            q.expect = f"{q.expect}, at least 3 places after the point"
        return q


def _base_spec(words: str) -> int:
    w = words.strip().lower().replace(" ", "")
    w = w.removeprefix("from").removeprefix("base")
    if w in _WORDS:
        return _WORDS[w]
    if re.fullmatch(r"b?\d+", w):
        b = int(w.lstrip("b"))
    elif re.fullmatch(r"[₀-₉]+", w):
        b = int(w.translate(_SUB))
    else:
        raise ValueError(f"unknown base {words.strip()!r} (use 2, 8, 10, 16 or bin, oct, dec, hex)")
    if not 2 <= b <= 16:
        raise ValueError("bases 2 to 16 only")
    return b


def _repeating_check(value: Fraction, base: int, want: Expansion) -> Callable[[str], Verdict]:
    """For a fraction that never terminates: accept a truncation (or rounding) of the expansion."""
    def check(text: str) -> Verdict:
        try:
            got, digits = read_numeral(text, base)
        except ValueError as e:
            return Verdict(False, str(e), retry=True)
        whole, _, frac = digits.partition(".")
        if len(frac) < 3:
            return Verdict(False, "this one never terminates: give at least 3 places after the point", retry=True)
        k = len(frac)
        truncated = value_of(f"{want.whole}.{want.digits(k)}", base)
        step = Fraction(1, base ** k)
        if got == truncated:
            return Verdict(True, f"(truncated to {k} places)")
        if got == truncated + step and value - truncated >= step / 2:
            return Verdict(True, f"(rounded to {k} places)")
        return Verdict(False)
    return check


@register
class TwosComplement(Topic):
    key, title, course = "twos", "Two's complement", "CIS 203"
    summary = "n-bit two's complement: encode, decode, add/subtract, overflow"
    solve_usage = "-45 bits=8 · 11010110 bits=8 · -45 + 23 bits=8 · 100 - 27 bits=8"

    _KINDS = {
        1: (["encode", "decode", "range"], [4, 4, 1]),
        2: (["encode", "decode", "arith", "overflow", "range"], [2, 2, 4, 3, 1]),
        3: (["encode", "decode", "arith", "overflow", "rep_encode", "rep_decode", "rep_range"],
            [1, 1, 3, 3, 2, 2, 1]),
    }

    def generate(self, rng: random.Random, level: int) -> Question:
        kinds, weights = self._KINDS[max(1, min(3, level))]
        kind = rng.choices(kinds, weights)[0]
        if kind == "encode":
            n = rng.choice([4, 8, 8, 8] if level == 1 else [8, 8, 8, 12, 16])
            lo = -(1 << (n - 1))
            v = lo if level >= 2 and rng.random() < 0.1 else -rng.randint(1, -lo - 1)
            return self.encode_question(v, n)
        if kind == "decode":
            n = rng.choice([4, 8, 8, 8] if level == 1 else [8, 8, 8, 12, 16])
            u = rng.randint(1 << (n - 1), (1 << n) - 1) if rng.random() < 0.85 else rng.randint(1, (1 << (n - 1)) - 1)
            return self.decode_question(bits_of(u, n))
        if kind == "range":
            return self.range_question(rng.choice([4, 5, 6, 8, 10, 12, 16]), "twos")
        if kind in ("arith", "overflow"):
            n = rng.choice([4, 6, 8, 8, 8] if level == 2 else [8, 8, 8, 12, 16])
            op = rng.choice("+-")
            lo, hi = tc_range(n)
            want_over = rng.random() < 0.5 if kind == "overflow" else rng.random() < 0.3
            edge = level >= 3 and op == "-" and rng.random() < 0.25
            for _ in range(1000):
                a = rng.randint(lo, hi)
                b = lo if edge else rng.randint(lo, hi)
                if min(abs(a), abs(b)) < 2 and not edge:
                    continue
                r = a + b if op == "+" else a - b
                if (not lo <= r <= hi) == want_over:
                    break
            as_bits = rng.random() < (0.3 if level == 2 else 0.4)
            if kind == "overflow":
                return self.overflow_question(a, b, op, n, as_bits)
            return self.arith_question(a, b, op, n, as_bits)
        rep = rng.choice(["sm", "ones"])
        if kind == "rep_range":
            return self.range_question(rng.choice([4, 5, 6, 8, 10, 12, 16]), rep)
        n = rng.choice([6, 8, 8])
        if kind == "rep_encode":
            return self.rep_encode_question(-rng.randint(1, (1 << (n - 1)) - 1), n, rep)
        if rng.random() < 0.06:
            pattern = "1" + "0" * (n - 1) if rep == "sm" else "1" * n          # negative zero
        else:
            pattern = bits_of(rng.randint((1 << (n - 1)) + 1, (1 << n) - 2), n)
        return self.rep_decode_question(pattern, rep)

    # ---- question builders (also used by solve) ----

    @staticmethod
    def encode_question(v: int, n: int, note: str = "") -> Question:
        p = tc_encode(v, n)
        lines = _encode_lines(v, n)
        slips = {}
        if v < 0:
            if -v < 1 << (n - 1):
                slips[ones_encode(v, n)] = "that's the one's complement: you inverted but didn't add 1"
                slips[sm_encode(v, n)] = "that's sign-magnitude; two's complement inverts +{0} and adds 1".format(-v)
                slips[bits_of(-v, n)] = f"that's +{-v}; negate it by inverting and adding 1"
                lines.append(f"(For comparison: sign-magnitude {group(sm_encode(v, n))}, "
                             f"one's complement {group(ones_encode(v, n))}.)")
        slips.pop(p, None)
        return Question(
            prompt=f"Write {v} as {_article(n)} {n}-bit two's complement number.{note}",
            expect=f"{n}-bit binary", check=_bits_check(p, slips), answer=group(p),
            solution="\n".join(lines),
            hint=f"Write +{abs(v)} in {n} bits, invert every bit, then add 1." if v < 0 else
                 f"A non-negative number is just its binary value with {n} bits.")

    @staticmethod
    def decode_question(bits: str, note: str = "") -> Question:
        n = len(bits)
        v = tc_decode(bits)
        lines = _decode_lines(bits)
        slips = {int(bits, 2): f"that's the unsigned value; in two's complement the MSB is worth -{1 << (n - 1)}",
                 ones_decode(bits): "that's the one's complement reading: after inverting, add 1",
                 sm_decode(bits): "that's the sign-magnitude reading",
                 -v: "check the sign: the MSB is " + bits[0]}
        if bits[0] == "1":
            lines.append(f"(Read as unsigned it would be {int(bits, 2)}; as sign-magnitude {sm_decode(bits)}; "
                         f"as one's complement {ones_decode(bits)}.)")
        slips.pop(v, None)
        return Question(
            prompt=f"What decimal value does the {n}-bit two's complement pattern {group(bits)} represent?{note}",
            expect="decimal", check=_int_check(v, slips), answer=str(v),
            solution="\n".join(lines),
            hint="MSB 1 means negative: invert and add 1 to get its size." if bits[0] == "1" else
                 "MSB 0 means positive: add up the place values.")

    @staticmethod
    def _arith_prompt(a: int, b: int, op: str, n: int, as_bits: bool) -> str:
        if as_bits:
            return f"{group(tc_encode(a, n))} {op} {group(tc_encode(b, n))}"
        return f"{a} {'−' if op == '-' else '+'} {_paren(b)}"

    def arith_question(self, a: int, b: int, op: str, n: int, as_bits: bool, note: str = "") -> Question:
        r = arith(a, b, op, n, given_as_bits=as_bits)
        what = self._arith_prompt(a, b, op, n, as_bits)
        return Question(
            prompt=f"Compute {what} in {n}-bit two's complement. Give the {n}-bit result.{note}",
            expect=f"{n}-bit binary", check=_arith_check(r), answer=group(r.result),
            solution="\n".join(r.lines),
            hint=("Add column by column and keep only the rightmost {0} bits.".format(n) if op == "+" else
                  "A − B = A + (two's complement of B): invert B, add 1, then add."))

    def overflow_question(self, a: int, b: int, op: str, n: int, as_bits: bool) -> Question:
        r = arith(a, b, op, n, given_as_bits=as_bits)
        what = self._arith_prompt(a, b, op, n, as_bits)
        return Question(
            prompt=f"In {n}-bit two's complement, does {what} overflow?",
            expect="yes/no", check=_yes_no_check(r.overflow), answer="yes" if r.overflow else "no",
            solution="\n".join(r.lines),
            hint="Do the addition; overflow means the carry into the MSB differs from the carry out of it.")

    @staticmethod
    def range_question(n: int, rep: str) -> Question:
        k = 1 << (n - 1)
        name = {"twos": "two's complement", "sm": "sign-magnitude", "ones": "one's complement"}[rep]
        if rep == "twos":
            lo, hi = -k, k - 1
            lines = [f"With {n} bits the MSB is worth -2{_sup(n - 1)} = {-k}; the other {n - 1} bits add up to at most "
                     f"2{_sup(n - 1)} - 1 = {k - 1}.",
                     f"Smallest: {group('1' + '0' * (n - 1))} = {lo}.   Largest: {group('0' + '1' * (n - 1))} = {hi}.",
                     f"Range: {lo} … {hi} ({1 << n} values, one more negative than positive)."]
            slips = {(-(k - 1), k - 1): "that's the sign-magnitude / one's complement range; two's complement "
                                        "has one more negative value",
                     (-k, k): f"the largest is 2{_sup(n - 1)} - 1, since 0 takes one of the non-negative patterns",
                     (0, (1 << n) - 1): "that's the unsigned range"}
            hint = f"The MSB is worth -2{_sup(n - 1)}; the other bits are ordinary positive place values."
        else:
            lo, hi = -(k - 1), k - 1
            zero = "1" + "0" * (n - 1) if rep == "sm" else "1" * n
            lines = [f"In {name} the largest magnitude fits in {n - 1} bits: 2{_sup(n - 1)} - 1 = {k - 1}.",
                     f"Range: {lo} … {hi}. Zero has two patterns: {group('0' * n)} (+0) and {group(zero)} (-0),",
                     f"so there are only {(1 << n) - 1} distinct values (two's complement gets {-k} instead)."]
            slips = {(-k, k - 1): f"that's the two's complement range; {name} wastes a pattern on -0"}
            hint = f"The sign bit is separate; the magnitude has {n - 1} bits."
        slips.pop((lo, hi), None)
        return Question(
            prompt=f"What range of values can {n}-bit {name} represent? Give the smallest and the largest.",
            expect="smallest largest", check=_range_check(lo, hi, slips), answer=f"{lo} to {hi}",
            solution="\n".join(lines), hint=hint)

    @staticmethod
    def rep_encode_question(v: int, n: int, rep: str) -> Question:
        m = -v
        pos = bits_of(m, n)
        if rep == "sm":
            p = sm_encode(v, n)
            lines = ["Sign-magnitude: the MSB is the sign (1 = negative); the other bits hold the size.",
                     f"{m} in {n - 1} bits: {m} = {_powers(m)} → {bits_of(m, n - 1)}",
                     f"Put the sign bit in front: 1 {bits_of(m, n - 1)} → {group(p)}"]
            slips = {ones_encode(v, n): "that's the one's complement (all bits inverted)",
                     tc_encode(v, n): "that's two's complement",
                     pos: f"that's +{m}: set the sign bit to 1"}
            hint = f"Sign bit 1, then {m} in {n - 1} bits."
        else:
            p = ones_encode(v, n)
            lines = ["One's complement: write +{0} in {1} bits and invert every bit.".format(m, n),
                     f"+{m} = {_powers(m)} → {group(pos)}",
                     f"Invert every bit → {group(p)}"]
            slips = {sm_encode(v, n): "that's sign-magnitude; one's complement inverts every bit",
                     tc_encode(v, n): "that's two's complement (inverted, then +1); one's complement stops "
                                      "after inverting",
                     pos: f"that's +{m}; invert every bit"}
            hint = f"Write +{m} in {n} bits, then invert every bit (no +1)."
        lines.append(f"(For comparison: sign-magnitude {group(sm_encode(v, n))}, one's complement "
                     f"{group(ones_encode(v, n))}, two's complement {group(tc_encode(v, n))}.)")
        slips.pop(p, None)
        name = "sign-magnitude" if rep == "sm" else "one's complement"
        return Question(prompt=f"Write {v} in {n}-bit {name}.", expect=f"{n}-bit binary",
                        check=_bits_check(p, slips), answer=group(p), solution="\n".join(lines), hint=hint)

    @staticmethod
    def rep_decode_question(bits: str, rep: str) -> Question:
        n = len(bits)
        if rep == "sm":
            v = sm_decode(bits)
            mag = bits[1:]
            lines = [f"Sign-magnitude: the MSB {bits[0]} is the sign" + (" (negative)." if bits[0] == "1" else "."),
                     f"Size: {mag} = {_powers(int(mag, 2))} = {int(mag, 2)}",
                     f"Value: {'-' if bits[0] == '1' else ''}{int(mag, 2)}" + (" (negative zero, which is 0)"
                                                                               if v == 0 and bits[0] == "1" else "")]
            hint = "The MSB is only the sign; read the other bits as an unsigned size."
        else:
            v = ones_decode(bits)
            inv = invert(bits)
            lines = [f"One's complement: the MSB {bits[0]} means " + ("negative." if bits[0] == "1" else "positive."),
                     f"Invert every bit to get the size: {group(inv)} = {_powers(int(inv, 2))} = {int(inv, 2)}",
                     f"Value: -{int(inv, 2)}" + (" (negative zero, which is 0)" if v == 0 else "")]
            hint = "MSB 1 means negative: invert every bit (no +1) to read the size."
        lines.append(f"(The same pattern in two's complement is {tc_decode(bits)}.)")
        slips = {tc_decode(bits): "that's the two's complement reading",
                 int(bits, 2): "that's the unsigned value"}
        if rep == "sm":
            slips[ones_decode(bits)] = "that's the one's complement reading"
        else:
            slips[sm_decode(bits)] = "that's the sign-magnitude reading"
        slips.pop(v, None)
        name = "sign-magnitude" if rep == "sm" else "one's complement"
        return Question(prompt=f"What decimal value does the {n}-bit {name} pattern {group(bits)} represent?",
                        expect="decimal", check=_int_check(v, slips), answer=str(v),
                        solution="\n".join(lines), hint=hint)

    # ---- calculator mode ----

    def solve(self, text: str) -> Question:
        t = text.translate(_DASHES)
        widths: list[int] = []

        def take(m: re.Match) -> str:
            widths.append(int(m.group(1)))
            return " "
        t = re.sub(r"(?i)\b(?:bits|width|n)\s*=\s*(\d+)\b", take, t)
        t = re.sub(r"(?i)\b(\d+)\s*-?\s*bits?\b", take, t)
        if len(set(widths)) > 1:
            raise ValueError("give the width once, e.g. bits=8")
        n = widths[0] if widths else None
        if n is not None and not 2 <= n <= 64:
            raise ValueError("width must be 2 to 64 bits")
        toks = re.findall(r"0[bB][01_]+|\d+|[+-]|\S+", t)
        for tok in toks:
            if not (tok in "+-" or tok[0].isdigit()):
                raise ValueError(f"can't read {tok!r}")
        pos = 0

        def operand() -> tuple[str, str]:
            nonlocal pos
            sign = ""
            if pos < len(toks) and toks[pos] in "+-":
                sign = toks[pos]
                pos += 1
            if pos >= len(toks) or not toks[pos][0].isdigit():
                raise ValueError("expected a number or a bit pattern")
            pos += 1
            return sign, toks[pos - 1]

        ops = [operand()]
        op = None
        if pos < len(toks):
            op = toks[pos]
            if op not in "+-":
                raise ValueError(f"expected + or -, got {op!r}")
            pos += 1
            ops.append(operand())
        if pos < len(toks):
            raise ValueError("one operation at a time: A + B or A - B")

        def pattern(sign: str, tok: str) -> str | None:
            if tok[:2].lower() == "0b":
                if sign:
                    raise ValueError("a bit pattern can't have a sign")
                return tok[2:].replace("_", "")
            if not sign and set(tok) <= {"0", "1"} and (len(tok) == n if n else len(tok) >= 4):
                return tok
            return None

        pats = [pattern(s, tok) for s, tok in ops]
        lens = {len(p) for p in pats if p is not None}
        if len(lens) > 1:
            raise ValueError("both patterns must have the same number of bits")
        if lens:
            plen = lens.pop()
            if n is not None and plen != n:
                raise ValueError(f"the pattern has {plen} bits but you said bits={n}")
            guessed = n is None and any(p is not None and not tok.lower().startswith("0b")
                                        for p, (_, tok) in zip(pats, ops))
            n = plen
        else:
            guessed = False
        ints = [tc_decode(p) if p is not None and n else None for p in pats]
        note = " (read as a bit pattern; for a decimal number add bits=N)" if guessed else ""
        if n is None:
            vals = [int(s + tok) for s, tok in ops]
            n = next((w for w in (8, 16, 32, 64) if all(tc_range(w)[0] <= v <= tc_range(w)[1] for v in vals)), 0)
            if not n:
                raise ValueError("that doesn't fit in 64 bits")
            note = f" ({n} bits by default; add bits=N for another width)"
        if not 2 <= n <= 64:
            raise ValueError("width must be 2 to 64 bits")
        lo, hi = tc_range(n)
        values = []
        for (sign, tok), p, iv in zip(ops, pats, ints):
            if p is not None:
                values.append(iv)
                continue
            v = int(sign + tok)
            if not lo <= v <= hi:
                raise ValueError(f"{v} doesn't fit in {n}-bit two's complement ({lo} … {hi})")
            values.append(v)
        if op is None:
            if pats[0] is not None:
                return self.decode_question(pats[0], note)
            return self.encode_question(values[0], n, note)
        as_bits = all(p is not None for p in pats)
        q = self.arith_question(values[0], values[1], op, n, as_bits, note)
        q.expect = f"{n}-bit binary [overflow yes/no]"
        q.answer = q.answer + ("  (overflow)" if arith(values[0], values[1], op, n).overflow else "  (no overflow)")
        return q
