"""dojo stress — stress-test a solution against a brute force on random tests."""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from dojo.commands import add_command
from dojo.commands.test import add_compare_flags, block, build_noted, clip, compare_mode, shell_path, show_warnings
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.run.lang import LANG_ORDER, LANGS
from dojo.run.stress import BRUTE_TL_FACTOR, StressResult, stress
from dojo.term import CHECK, CROSS, Term

TEMPLATES = Path(__file__).resolve().parents[1] / "run" / "templates"
INPUT_LINES = 30


def register(sub, common):
    p = add_command(sub, common, "stress", "stress-test a solution against a brute force",
                    description="Run your solution and a brute force on many small random tests until they\n"
                                "disagree, then show that test.\n\n"
                                "Why: a wrong answer with no failing test is the biggest time sink in CP.\n"
                                "Resubmitting with guesses costs attempts; a slow-but-obviously-correct brute\n"
                                "force plus a random generator usually finds a failing case in seconds, small\n"
                                "enough to trace by hand.\n\n"
                                "Files next to the solution (C++, C, Java or Python):\n"
                                "  brute.* or <name>_brute.*   simplest correct solution (any speed)\n"
                                "  gen.*   or <name>_gen.*     prints one random test; gets the seed as argv[1]\n"
                                "`--init` writes brute.cpp (your template) and gen.py to start from.\n"
                                "Python generators can `from dojo.gen import *` (rint, rarray, perm, tree_edges, out…).\n\n"
                                "On a failure the test is saved as stress/fail.in (+ fail.out yours, fail.ans\n"
                                "the brute force's) next to the solution: `dojo test sol.cpp stress/fail.in`.")
    p.add_argument("file", type=Path, help="your solution")
    p.add_argument("--brute", type=Path, help="brute force (default: brute.* or <name>_brute.* next to it)")
    p.add_argument("--gen", type=Path, help="generator (default: gen.* or <name>_gen.* next to it)")
    p.add_argument("-n", type=int, default=500, help="number of random tests (default 500)")
    p.add_argument("--tl", type=float, default=2.0,
                   help=f"time limit for your solution in seconds (default 2; the brute force gets {BRUTE_TL_FACTOR}×)")
    p.add_argument("--seed", type=int, default=1, help="first generator seed (default 1)")
    p.add_argument("--debug", action="store_true", help="build your solution with sanitizers and the checked STL")
    p.add_argument("--checker", type=Path, help="testlib-style checker (`checker in out ans`, exit 0 = accepted),\n"
                                                "for problems with several correct answers")
    add_compare_flags(p)
    p.add_argument("--init", action="store_true", help="write brute.cpp and gen.py next to the solution, then stop")
    p.add_argument("--json", action="store_true", help="print the result as JSON (dojo web uses this)")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    a, term = ctx.args, ctx.term
    sol_path = a.file.expanduser()
    if not sol_path.is_file():
        raise DojoError(f"no such file: {a.file}")
    if a.init:
        return init_files(term, sol_path)
    if a.n < 1:
        raise DojoError("-n must be at least 1")
    if a.tl <= 0:
        raise DojoError("--tl must be positive")
    mode, eps = compare_mode(a)
    brute_path = _given(a.brute, "brute force") or find_partner(sol_path, "brute")
    gen_path = _given(a.gen, "generator") or find_partner(sol_path, "gen")
    if brute_path is None:
        raise DojoError(f"no brute force next to {sol_path.name}: write brute.cpp (the simplest correct solution) "
                        f"or {sol_path.stem}_brute.cpp — `dojo stress {shell_path(sol_path)} --init` starts both files")
    if gen_path is None:
        raise DojoError(f"no generator next to {sol_path.name}: write gen.py (prints one random test, seed in argv[1]) "
                        f"— `dojo stress {shell_path(sol_path)} --init` starts one")
    if brute_path.resolve() == sol_path.resolve():
        raise DojoError("the brute force is the solution itself — pass a different file with --brute")

    try:
        sol = build_noted(term, sol_path, debug=a.debug)
        brute = build_noted(term, brute_path)
        gen = build_noted(term, gen_path)
        checker = build_noted(term, a.checker) if a.checker else None
    except DojoError as e:
        if not a.json:
            raise
        term.out(json.dumps({"file": sol_path.name, "error": str(e), "stage": "build"}))
        return 1
    if a.json:
        res = stress(sol, brute, gen, n=a.n, tl=a.tl, mode=mode, eps=eps, checker=checker, seed0=a.seed)
        saved = None if res.ok else save_failure(res, sol_path)
        term.out(json.dumps({
            "file": sol_path.name, "brute": brute_path.name, "gen": gen_path.name, "n": a.n, "tl": a.tl,
            "debug": a.debug, "ok": res.ok, "iterations": res.iterations, "verdict": res.verdict,
            "reason": res.reason, "seed": res.seed, "input": clip(res.failing_input),
            "expected": clip(res.expected), "got": clip(res.got), "stderr": clip(res.stderr),
            "max_seconds": round(res.max_seconds, 4), "brute_max_seconds": round(res.brute_max_seconds, 4),
            "distinct": res.distinct, "saved": str(saved) if saved else None,
            "warnings": [ln for ln in sol.warnings.splitlines() if "warning:" in ln]}))
        return 0 if res.ok else 1

    term.out(term.title(sol_path.name) + term.muted(
        f"  vs {brute_path.name} · {a.n} tests from {gen_path.name} · seeds {a.seed}–{a.seed + a.n - 1}"
        f" · tl {a.tl:g} s" + (" · debug build" if a.debug else "")))
    show_warnings(term, sol)

    progress = Progress(term, a.n)
    try:
        res = stress(sol, brute, gen, n=a.n, tl=a.tl, mode=mode, eps=eps, checker=checker,
                     seed0=a.seed, on_progress=progress)
    except KeyboardInterrupt:
        progress.clear()
        term.out(term.s(f"stopped after {progress.done} test{'s' if progress.done != 1 else ''}", "warn")
                 + term.muted(" — all passed so far"))
        return 130
    finally:
        progress.clear()

    if res.ok:
        term.out(term.s(f"{CHECK} {res.iterations}/{res.iterations} random tests passed", "good", "bold")
                 + term.muted(f"  your slowest {res.max_seconds:.2f} s · brute force {res.brute_max_seconds:.2f} s"))
        if res.distinct == 1 and res.iterations > 1:
            term.out(term.s("! every test was the same — make the generator use its seed "
                            "(seed_from_argv() from dojo.gen, or argv[1])", "warn"))
        else:
            term.out(term.muted("Still WA on Codeforces? Widen the generator (n = 1, equal values, max values) "
                                "and stress again."))
        return 0
    report_failure(term, res, sol_path, brute_path, a)
    return 1


def report_failure(term: Term, res: StressResult, sol_path: Path, brute_path: Path, a) -> None:
    passed = res.iterations - 1
    what = {"WA": "Wrong answer", "TLE": "Time limit exceeded", "RE": "Runtime error",
            "BRUTE": "The brute force failed"}.get(res.verdict or "", "Failed")
    term.out(term.s(f"{CROSS} {what} on test {res.iterations}", "bad", "bold")
             + term.muted(f"  seed {res.seed} · {passed} passed before it"))
    if res.reason:
        term.out("  " + res.reason)
    term.out(block(term, "input", res.failing_input or "", limit=INPUT_LINES))
    if res.verdict == "BRUTE":
        if res.stderr.strip():
            term.out(block(term, f"stderr ({brute_path.name})", res.stderr, stderr=True))
    else:
        term.out(block(term, f"expected ({brute_path.name})", res.expected or ""),
                 block(term, "yours", res.got or ""))
        if res.stderr.strip():
            term.out(block(term, "stderr", res.stderr, stderr=True))

    folder = sol_path.parent / "stress"
    try:
        save_failure(res, sol_path, strict=True)
    except OSError as e:
        term.warn(f"couldn't save the failing test in {folder}: {e.strerror}")
        return
    flags = (" --debug" if a.debug else "") + (f" --float {a.eps:g}" if a.eps is not None else "") \
        + (" --exact" if a.exact else "")
    term.out("")
    term.out(term.muted(f"saved {shell_path(folder)}/fail.in, fail.out (yours), fail.ans ({brute_path.name})"))
    term.out(term.muted("re-run: ") + f"dojo test {shell_path(sol_path)} {shell_path(folder / 'fail.in')}{flags}")


def save_failure(res: StressResult, sol_path: Path, *, strict: bool = False) -> Path | None:
    """Write stress/fail.in, fail.out (yours) and fail.ans (the brute force's) next to the solution."""
    folder = sol_path.parent / "stress"
    try:
        folder.mkdir(exist_ok=True)
        (folder / "fail.in").write_text(res.failing_input or "")
        (folder / "fail.out").write_text(res.got or "")
        (folder / "fail.ans").write_text(res.expected or "")
    except OSError:
        if strict:
            raise
        return None
    return folder / "fail.in"


class Progress:
    """One self-updating stderr line, only on a terminal."""

    def __init__(self, term: Term, n: int):
        self.term, self.n, self.done = term, n, 0
        self.tty = sys.stderr.isatty()
        self.t0 = self.last = time.monotonic()
        self.shown = False

    def __call__(self, done: int, n: int) -> None:
        self.done = done
        now = time.monotonic()
        if not self.tty or (now - self.last < 0.1 and done < n):
            return
        self.last = now
        rate = done / max(1e-9, now - self.t0)
        sys.stderr.write("\r\x1b[K" + self.term.muted(f"  {done}/{n} passed · {rate:.0f} tests/s"))
        sys.stderr.flush()
        self.shown = True

    def clear(self) -> None:
        if self.shown:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()
            self.shown = False


# ---- finding and creating the helper files ----------------------------------------------

def _given(p: Path | None, what: str) -> Path | None:
    if p is None:
        return None
    p = p.expanduser()
    if not p.is_file():
        raise DojoError(f"no such {what}: {p}")
    return p


def find_partner(sol: Path, role: str) -> Path | None:
    """`<stem>_<role>.*`, then `<role>.*`, next to the solution (C++ before C, Java, Python)."""
    suffixes = sorted(LANGS, key=lambda s: LANG_ORDER.index(LANGS[s]))
    for stem in (f"{sol.stem}_{role}", role):
        for suffix in suffixes:
            p = sol.parent / f"{stem}{suffix}"
            if p.is_file() and p.resolve() != sol.resolve():
                return p
    return None


def init_files(term: Term, sol: Path) -> int:
    for role, template, note in (("brute", "brute.cpp", "your template; write the simplest correct solution"),
                                 ("gen", "gen.py", "prints one small random test from its seed")):
        existing = find_partner(sol, role)
        if existing is not None:
            term.out(f"  {term.muted('kept')}  {shell_path(existing)}" + term.muted("  (already exists)"))
            continue
        dest = sol.parent / template
        try:
            shutil.copyfile(TEMPLATES / template, dest)
        except OSError as e:
            raise DojoError(f"couldn't write {dest}: {e.strerror}") from None
        term.out(f"  {term.s('wrote', 'good')} {shell_path(dest)}" + term.muted(f"  {note}"))
    term.out(term.muted(f"then: dojo stress {shell_path(sol)}"))
    return 0
