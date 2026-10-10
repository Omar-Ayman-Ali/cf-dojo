"""Terminal output: colour, Codeforces rank colours, links, tables, bars, sparklines.

Every command prints through a Term so NO_COLOR, pipes and --no-color all behave the same.
Styles are names from PALETTE, 'bold' / 'dim' / 'italic' / 'underline', or a '#rrggbb' colour.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from typing import Iterable, Sequence

# Dark-themed terminal palette.
PALETTE = {
    "accent": "#c8f169",
    "good": "#7fd37f",
    "bad": "#ff6b6b",
    "warn": "#e3b341",
    "info": "#6cc4e0",
    "muted": "#9aa1a9",
    "violet": "#b58cff",
    "orange": "#f0884a",
}
_BASIC = {"accent": "92", "good": "32", "bad": "31", "warn": "33", "info": "36", "muted": "90",
          "violet": "35", "orange": "33"}
_ATTR = {"bold": "1", "dim": "2", "italic": "3", "underline": "4"}

# Codeforces ranks: (lowest rating, name, colour).
RANKS = [
    (3000, "legendary grandmaster", "#ff3b3b"),
    (2600, "international grandmaster", "#ff3b3b"),
    (2400, "grandmaster", "#ff3b3b"),
    (2300, "international master", "#ffab40"),
    (2100, "master", "#ffab40"),
    (1900, "candidate master", "#c264ff"),
    (1600, "expert", "#6f8cff"),
    (1400, "specialist", "#3fc1b0"),
    (1200, "pupil", "#5fbf5f"),
    (-10**9, "newbie", "#a8a8a8"),
]

_ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;.*?\x1b\\")

CHECK, CROSS, DOT, ARROW = "✓", "✗", "·", "→"


def rank_of(rating: int | None) -> tuple[str, str]:
    """(rank name, colour) for a rating; unrated counts as newbie."""
    r = -10**9 if rating is None else rating
    for low, name, colour in RANKS:
        if r >= low:
            return name, colour
    return RANKS[-1][1], RANKS[-1][2]


def next_rank(rating: int | None) -> tuple[int, str] | None:
    """(rating needed, rank name) for the next rank up, or None at the top."""
    r = -10**9 if rating is None else rating
    for low, name, _ in reversed(RANKS):
        if low > r:
            return low, name
    return None


def strip(text: str) -> str:
    return _ANSI.sub("", text)


def width_of(text: str) -> int:
    """Display width: ANSI codes are free, East Asian wide chars and most emoji take two cells."""
    w = 0
    for ch in strip(text):
        if unicodedata.combining(ch) or ch in "‍️︎":
            continue
        w += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return w


def truncate(text: str, width: int) -> str:
    """Cut plain text to `width` cells with an ellipsis. Don't pass styled text."""
    if width_of(text) <= width:
        return text
    out, w = [], 0
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if w + cw > width - 1:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


def pad(text: str, width: int, align: str = "l") -> str:
    gap = max(0, width - width_of(text))
    if align == "r":
        return " " * gap + text
    if align == "c":
        return " " * (gap // 2) + text + " " * (gap - gap // 2)
    return text + " " * gap


class Term:
    def __init__(self, *, color: bool | None = None, links: bool | None = None,
                 width: int | None = None, stream=None):
        self.stream = stream or sys.stdout
        tty = bool(getattr(self.stream, "isatty", lambda: False)())
        if color is None:
            if os.environ.get("NO_COLOR"):
                color = False
            elif os.environ.get("FORCE_COLOR"):
                color = True
            else:
                color = tty and os.environ.get("TERM") != "dumb"
        self.color = color
        self.truecolor = color and os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        if links is None:
            links = color and tty and not os.environ.get("DOJO_NO_LINKS")
        self.links = links
        self.width = width or shutil.get_terminal_size((100, 24)).columns

    # ---- styling ---------------------------------------------------------------

    def s(self, text: object, *styles: str | None) -> str:
        text = str(text)
        if not self.color:
            return text
        codes = []
        for st in styles:
            if not st:
                continue
            if st in _ATTR:
                codes.append(_ATTR[st])
            elif st in PALETTE or st.startswith("#"):
                codes.append(self._fg(st))
            else:
                raise ValueError(f"unknown style {st!r}")
        if not codes:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    def _fg(self, st: str) -> str:
        hexcol = PALETTE.get(st, st)
        r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
        if self.truecolor:
            return f"38;2;{r};{g};{b}"
        if st in _BASIC:
            return _BASIC[st]
        # xterm-256 colour cube
        q = lambda v: 0 if v < 48 else 1 if v < 115 else (v - 35) // 40
        return f"38;5;{16 + 36 * q(r) + 6 * q(g) + q(b)}"

    def rating(self, rating: int | None, text: object | None = None) -> str:
        """A rating (or `text`) in its Codeforces rank colour."""
        shown = text if text is not None else ("unrated" if rating is None else rating)
        return self.s(shown, rank_of(rating)[1], "bold")

    def link(self, text: str, url: str | None) -> str:
        """OSC 8 hyperlink: clickable in Alacritty, Ghostty, kitty, foot, VS Code."""
        if not url or not self.links:
            return text
        return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"

    # ---- building blocks ---------------------------------------------------------

    def bar(self, frac: float, width: int = 24, style: str = "accent") -> str:
        frac = 0.0 if frac != frac else min(1.0, max(0.0, frac))
        full = round(frac * width)
        return self.s("█" * full, style) + self.s("░" * (width - full), "muted")

    @staticmethod
    def spark(values: Sequence[float]) -> str:
        if not values:
            return ""
        blocks = "▁▂▃▄▅▆▇█"
        lo, hi = min(values), max(values)
        if hi == lo:
            return (blocks[0] if hi == 0 else blocks[3]) * len(values)
        return "".join(blocks[round((v - lo) / (hi - lo) * (len(blocks) - 1))] for v in values)

    def title(self, text: str) -> str:
        return self.s(text, "accent", "bold")

    def section(self, text: str) -> str:
        return "\n" + self.s(text.upper(), "muted", "bold")

    def muted(self, text: object) -> str:
        return self.s(text, "muted")

    def kv(self, pairs: Iterable[tuple[str, str]], indent: int = 2) -> str:
        pairs = list(pairs)
        if not pairs:
            return ""
        w = max(width_of(k) for k, _ in pairs)
        return "\n".join(" " * indent + self.s(pad(k, w), "muted") + "  " + v for k, v in pairs)

    def table(self, rows: Sequence[Sequence[str]], *, header: Sequence[str] | None = None,
              align: str | None = None, indent: int = 2, gap: int = 2) -> str:
        """Rows of (possibly styled) cells. `align` is one letter per column: l, r or c."""
        all_rows = ([list(header)] if header else []) + [list(map(str, r)) for r in rows]
        if not all_rows:
            return ""
        ncol = max(len(r) for r in all_rows)
        for r in all_rows:
            r.extend([""] * (ncol - len(r)))
        widths = [max(width_of(r[i]) for r in all_rows) for i in range(ncol)]
        align = (align or "").ljust(ncol, "l")
        out = []
        for n, r in enumerate(all_rows):
            cells = [pad(c, widths[i], align[i]) for i, c in enumerate(r)]
            line = (" " * gap).join(cells).rstrip()
            if header and n == 0:
                line = self.s(strip(line), "muted")
            out.append(" " * indent + line)
        return "\n".join(out)

    # ---- output ------------------------------------------------------------------

    def out(self, *lines: str) -> None:
        print(*lines, sep="\n", file=self.stream, flush=True)

    def err(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def note(self, msg: str) -> None:
        """Progress / diagnostics to stderr, so stdout stays clean for pipes and --json."""
        self.err(self.s(msg, "muted") if self.color else msg)

    def warn(self, msg: str) -> None:
        self.err(self.s("warning: ", "warn", "bold") + msg)
