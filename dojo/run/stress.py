"""Stress testing: run your solution and a brute force on random tests until they disagree.

    res = stress(sol, brute, gen, n=500, tl=2.0, mode="tokens", eps=1e-6)
    if not res.ok:
        print(res.failing_input, res.expected, res.got, res.reason)

Test i (from seed0) is `gen <seed0 + i>`'s stdout, so a failing seed is reproducible. The brute
force gets 10× the time limit; a brute force that crashes or times out is reported as such.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dojo.errors import DojoError
from dojo.run.judge import judge, run
from dojo.run.lang import Program

BRUTE_TL_FACTOR = 10
GEN_TL = 10.0


@dataclass
class StressResult:
    ok: bool
    iterations: int                     # tests run, including the failing one
    failing_input: str | None = None
    expected: str | None = None         # brute force's output
    got: str | None = None              # your output
    reason: str | None = None           # first difference, or what went wrong
    seed: int | None = None             # generator seed of the failing test
    verdict: str | None = None          # "WA" | "TLE" | "RE" | "BRUTE" (the brute force failed)
    stderr: str = ""                    # your program's stderr on the failing test
    max_seconds: float = 0.0            # slowest run of your solution
    brute_max_seconds: float = 0.0
    distinct: int = 0                   # different inputs the generator printed (1 = it ignores the seed)


def stress(sol: Program, brute: Program, gen: Program, *, n: int, tl: float, mode: str, eps: float,
           checker: Program | None = None, seed0: int = 1,
           on_progress: Callable[[int, int], None] | None = None) -> StressResult:
    """Up to `n` random tests; stops at the first wrong answer, crash or timeout.
    `on_progress(done, n)` is called after each passing test. Generator failures raise DojoError."""
    worst = brute_worst = 0.0
    seen: set[int] = set()
    for i in range(n):
        seed = seed0 + i
        g = run(gen, "", tl=GEN_TL, args=[str(seed)])
        if g.timed_out or g.crashed:
            detail = _first_lines(g.stderr, 8)
            raise DojoError(f"generator {gen.name} failed on seed {seed}: {g.describe()}"
                            + (f"\n{detail}" if detail else ""))
        test = g.stdout
        seen.add(hash(test))
        b = run(brute, test, tl=tl * BRUTE_TL_FACTOR)
        s = run(sol, test, tl=tl)
        worst = max(worst, s.seconds)
        brute_worst = max(brute_worst, b.seconds)
        base = dict(iterations=i + 1, failing_input=test, expected=b.stdout, got=s.stdout, seed=seed,
                    stderr=s.stderr, max_seconds=worst, brute_max_seconds=brute_worst, distinct=len(seen))
        if b.timed_out or b.crashed:
            return StressResult(ok=False, verdict="BRUTE",
                                reason=f"the brute force failed: {b.describe()}"
                                       + (f" (over {tl * BRUTE_TL_FACTOR:g} s)" if b.timed_out else "")
                                       + " — make it handle this input, or make the generator's tests smaller",
                                **{**base, "stderr": b.stderr})
        verdict, msg = judge(s, b.stdout, mode=mode, eps=eps, checker=checker, stdin=test)
        if verdict != "AC":
            if verdict == "TLE":
                msg = f"time limit exceeded (over {tl:g} s)"
            return StressResult(ok=False, verdict=verdict, reason=msg, **base)
        if on_progress:
            on_progress(i + 1, n)
    return StressResult(ok=True, iterations=n, max_seconds=worst, brute_max_seconds=brute_worst,
                        distinct=len(seen))


def _first_lines(text: str, k: int) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[:k])
