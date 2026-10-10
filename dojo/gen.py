"""Helpers for random test generators used by `dojo stress`.

    # gen.py — prints one test; `dojo stress` runs it as `gen.py <seed>`
    from dojo.gen import *

    seed_from_argv()
    n = rint(1, 8)
    out(n, rarray(n, 1, 10))

Everything is seeded from argv[1] (also at import), so `python3 gen.py 17` always prints the same
test, and the global `random` module is seeded too in case you use it directly.
Small tests find bugs fastest: keep n and the values tiny.
"""
from __future__ import annotations

import random
import sys
from typing import Sequence

__all__ = ["rng", "seed_from_argv", "rint", "rfloat", "chance", "choice", "shuffle", "rarray", "perm",
           "rstring", "distinct", "tree_edges", "graph_edges", "out"]

rng = random.Random()


def seed_from_argv(default: int = 1) -> int:
    """Seed from argv[1] (an integer; other text works too). Returns the integer seed, or
    `default` when argv[1] is missing or not a number."""
    arg = sys.argv[1] if len(sys.argv) > 1 else str(default)
    try:
        seed: int | str = int(arg)
    except ValueError:
        seed = arg
    rng.seed(seed)
    random.seed(seed)
    return seed if isinstance(seed, int) else default


def rint(lo: int, hi: int) -> int:
    """Uniform integer in [lo, hi]."""
    return rng.randint(lo, hi)


def rfloat(lo: float, hi: float, digits: int = 2) -> float:
    return round(rng.uniform(lo, hi), digits)


def chance(p: float) -> bool:
    """True with probability p."""
    return rng.random() < p


def choice(seq: Sequence):
    return rng.choice(seq)


def shuffle(items: list) -> list:
    """Shuffles in place and returns the list."""
    rng.shuffle(items)
    return items


def rarray(n: int, lo: int, hi: int) -> list[int]:
    """n integers, each uniform in [lo, hi]."""
    return [rng.randint(lo, hi) for _ in range(n)]


def perm(n: int, start: int = 1) -> list[int]:
    """A random permutation of start..start+n-1 (1..n by default)."""
    p = list(range(start, start + n))
    rng.shuffle(p)
    return p


def rstring(n: int, alphabet: str = "abc") -> str:
    """n characters from `alphabet` (small alphabets hit more corner cases)."""
    return "".join(rng.choice(alphabet) for _ in range(n))


def distinct(n: int, lo: int, hi: int) -> list[int]:
    """n distinct integers from [lo, hi], in random order."""
    if n > hi - lo + 1:
        raise ValueError(f"can't pick {n} distinct values from [{lo}, {hi}]")
    return rng.sample(range(lo, hi + 1), n)


def tree_edges(n: int) -> list[tuple[int, int]]:
    """n-1 edges of a random tree on vertices 1..n (random labels, edge order and directions)."""
    label = perm(n)
    edges = []
    for v in range(1, n):
        u = rng.randint(0, v - 1)
        a, b = label[u], label[v]
        edges.append((a, b) if rng.random() < 0.5 else (b, a))
    rng.shuffle(edges)
    return edges


def graph_edges(n: int, m: int, connected: bool = False) -> list[tuple[int, int]]:
    """m edges of a random simple undirected graph on 1..n (no loops, no repeated edges).
    connected=True starts from a random spanning tree, so it needs m >= n - 1."""
    most = n * (n - 1) // 2
    if m > most:
        raise ValueError(f"a simple graph on {n} vertices has at most {most} edges, not {m}")
    if connected and n > 0 and m < n - 1:
        raise ValueError(f"a connected graph on {n} vertices needs at least {n - 1} edges, not {m}")
    edges = tree_edges(n) if connected and n > 1 else []
    seen = {frozenset(e) for e in edges}
    if m - len(edges) > most // 2:
        rest = [(a, b) for a in range(1, n + 1) for b in range(a + 1, n + 1) if frozenset((a, b)) not in seen]
        rng.shuffle(rest)
        edges += rest[:m - len(edges)]
    else:
        while len(edges) < m:
            a, b = rng.randint(1, n), rng.randint(1, n)
            if a != b and frozenset((a, b)) not in seen:
                seen.add(frozenset((a, b)))
                edges.append((a, b))
    rng.shuffle(edges)
    return [(a, b) if rng.random() < 0.5 else (b, a) for a, b in edges]


def _row(x) -> str:
    if isinstance(x, (list, tuple)):
        return " ".join(map(str, x))
    return str(x)


def out(*rows) -> None:
    """Print each argument on its own line. A list/tuple prints space-separated; a list of
    lists/tuples (edges, a grid) prints one line per item.

        out(n, m)            # two lines
        out(f"{n} {m}")      # one line
        out(rarray(5, 1, 9)) # 3 1 4 1 5
        out(tree_edges(4))   # 3 lines: "a b"
    """
    lines = []
    for r in rows:
        if isinstance(r, (list, tuple)) and r and all(isinstance(x, (list, tuple)) for x in r):
            lines.extend(_row(x) for x in r)
        else:
            lines.append(_row(r))
    sys.stdout.write("\n".join(lines) + "\n")


seed_from_argv()
