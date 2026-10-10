"""dojo test — run a solution on its samples: CPH's, your own .in/.out files, or stdin."""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.run import cph
from dojo.run.judge import judge, run as run_prog
from dojo.run.lang import Program, build
from dojo.term import CHECK, CROSS, Term, truncate

DEFAULT_TL = 2.0
DEBUG_TL_FACTOR = 5          # sanitizers and the checked STL slow programs down a lot
BLOCK_LINES = 12
JSON_TEXT_LIMIT = 4000       # characters of input/output kept per test in --json
ANSWER_SUFFIXES = (".ans", ".out", ".answer")     # .ans first: stress writes fail.out = yours


def register(sub, common):
    p = add_command(sub, common, "test", "run a solution on its samples",
                    description="Build a solution and run it on its samples: the ones Competitive Programming\n"
                                "Helper saved in .cph/ next to the file, or input files you name (a.in is\n"
                                "checked against a.out or a.ans), or piped stdin. Exit code 1 if any test fails.\n\n"
                                "examples:\n"
                                "  dojo test A_Koshary.cpp\n"
                                "  dojo test A_Koshary.cpp stress/fail.in\n"
                                "  dojo test A_Koshary.cpp tests/          # every .in file in tests/\n"
                                "  dojo test Main.java < input.txt")
    p.add_argument("file", type=Path, help="solution (.cpp, .c, .java, .py)")
    p.add_argument("inputs", nargs="*", type=Path, help="input files or folders of .in files ('-' = stdin)")
    p.add_argument("--tl", type=float, help="time limit in seconds (default: the problem's, from CPH, else 2)")
    p.add_argument("--debug", action="store_true",
                   help="build with -g, AddressSanitizer/UBSan and the checked STL: they name the line\n"
                        "that indexes out of bounds or overflows (time limit ×5)")
    add_compare_flags(p)
    p.add_argument("--checker", type=Path, help="testlib-style checker: `checker in out ans`, exit 0 = accepted")
    p.add_argument("--json", action="store_true", help="print the results as JSON (dojo web uses this)")
    p.set_defaults(func=run)


def add_compare_flags(p) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--float", type=float, metavar="EPS", dest="eps",
                   help="compare numbers with absolute or relative error EPS (e.g. 1e-6)")
    g.add_argument("--exact", action="store_true", help="compare line by line (default: token by token)")


def compare_mode(a) -> tuple[str, float]:
    if a.eps is not None:
        if a.eps < 0:
            raise DojoError("--float needs a non-negative EPS, like 1e-6")
        return "float", a.eps
    return ("exact" if a.exact else "tokens"), 1e-6


def run(ctx: Ctx) -> int:
    a, term = ctx.args, ctx.term
    if a.tl is not None and a.tl <= 0:
        raise DojoError("--tl must be positive")
    mode, eps = compare_mode(a)
    src = a.file.expanduser()
    if not src.is_file():
        raise DojoError(f"no such file: {a.file}")
    tests, source, doc = collect_tests(src, a.inputs)
    tl = a.tl or cph.cph_time_limit(doc) or DEFAULT_TL
    if a.debug and a.tl is None:
        tl *= DEBUG_TL_FACTOR
    try:
        prog = build_noted(term, src, debug=a.debug)
        checker = build_noted(term, a.checker) if a.checker else None
    except DojoError as e:
        if not a.json:
            raise
        term.out(json.dumps({"file": src.name, "error": str(e), "stage": "build", "tests": []}))
        return 1
    if a.json:
        return run_json(term, a, src, prog, checker, tests, source, tl, mode, eps)

    header = [f"{len(tests)} test{'s' if len(tests) != 1 else ''} from {source}", f"tl {tl:g} s"]
    if a.debug:
        header.append("debug build")
    if mode != "tokens":
        header.append(f"compare {mode}" + (f" ±{eps:g}" if mode == "float" else ""))
    term.out(term.title(src.name) + term.muted("  " + " · ".join(header)))
    show_warnings(term, prog)

    failed: list[tuple[str, str]] = []
    slowest = 0.0
    for label, stdin, ans in tests:
        res = run_prog(prog, stdin, tl=tl)
        verdict, msg = judge(res, ans, mode=mode, eps=eps, checker=checker, stdin=stdin)
        slowest = max(slowest, res.seconds)
        term.out(verdict_line(term, verdict, label, res.seconds, tl, msg))
        if verdict in ("WA", "RE", "TLE"):
            failed.append((label, verdict))
            if verdict == "WA" or len(tests) == 1:
                term.out(block(term, "input", stdin))
            if verdict == "WA":
                term.out(block(term, "expected", ans or ""), block(term, "yours", res.stdout))
        elif verdict == "RAN":
            term.out(block(term, "output", res.stdout, limit=40))
        if res.stderr.strip():
            term.out(block(term, "stderr", res.stderr, stderr=True))

    term.out("")
    judged = sum(1 for _, _, ans in tests if ans is not None)
    if failed:
        what = ", ".join(f"{v} on {lbl}" for lbl, v in failed[:4]) + (" …" if len(failed) > 4 else "")
        term.out(term.s(f"{CROSS} {len(failed)} of {len(tests)} failed", "bad", "bold") + term.muted(f"  {what}"))
        kinds = {v for _, v in failed}
        if "RE" in kinds and not a.debug and prog.lang in ("cpp", "c"):
            term.out(term.muted(f"Crash? `dojo test {shell_path(src)} --debug` names the line that went out of bounds."))
        elif "TLE" in kinds:
            term.out(term.muted("Too slow: count the operations for the largest n before optimising constants."))
        return 1
    if judged:
        term.out(term.s(f"{CHECK} {judged}/{judged} passed", "good", "bold")
                 + term.muted(f"  slowest {slowest:.2f} s of {tl:g} s"))
        from dojo.commands.stress import find_partner
        ready = find_partner(src, "brute") and find_partner(src, "gen")
        term.out(term.muted(f"Samples are the easy cases. Before submitting: dojo stress {shell_path(src)}"
                            + ("" if ready else " --init")))
    elif source == "your files":
        term.out(term.muted("nothing to compare against: put the expected output in a .ans or .out file next to the .in"))
    return 0


def run_json(term: Term, a, src: Path, prog: Program, checker: Program | None, tests, source: str,
             tl: float, mode: str, eps: float) -> int:
    """The same runs and verdicts as the terminal report, as one JSON document."""
    rows = []
    for label, stdin, ans in tests:
        res = run_prog(prog, stdin, tl=tl)
        verdict, msg = judge(res, ans, mode=mode, eps=eps, checker=checker, stdin=stdin)
        rows.append({"label": label, "verdict": verdict, "seconds": round(res.seconds, 4), "message": msg,
                     "input": clip(stdin), "expected": clip(ans) if ans is not None else None,
                     "got": clip(res.stdout), "stderr": clip(res.stderr)})
    failed = [r for r in rows if r["verdict"] in ("WA", "RE", "TLE")]
    term.out(json.dumps({
        "file": src.name, "path": str(src.resolve()), "lang": prog.lang, "source": source, "tl": tl,
        "debug": a.debug, "mode": mode, "warnings": [ln for ln in prog.warnings.splitlines() if "warning:" in ln],
        "tests": rows, "judged": sum(1 for r in rows if r["expected"] is not None), "failed": len(failed),
        "slowest": round(max((r["seconds"] for r in rows), default=0.0), 4)}))
    return 1 if failed else 0


def clip(text: str | None, limit: int = JSON_TEXT_LIMIT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n… {len(text) - limit} more characters"


# ---- tests -----------------------------------------------------------------------------

def collect_tests(src: Path, inputs: list[Path]) -> tuple[list[tuple[str, str, str | None]], str, dict | None]:
    """[(label, input, expected or None)], where they came from, and the CPH record (for its time limit)."""
    doc = cph.cph_problem(src)
    if inputs:
        tests: list[tuple[str, str, str | None]] = []
        for p in inputs:
            if str(p) == "-":
                tests.append(("stdin", sys.stdin.read(), None))
            elif p.is_dir():
                found = sorted(p.glob("*.in"))
                if not found:
                    raise DojoError(f"no .in files in {p}")
                tests += [_file_test(f) for f in found]
            elif p.is_file():
                tests.append(_file_test(p))
            else:
                raise DojoError(f"no such input file: {p}")
        return tests, "your files", doc
    samples = cph.cph_tests(src) or []
    if samples:
        return [(f"#{i}", inp, out) for i, (inp, out) in enumerate(samples, 1)], "CPH", doc
    if not sys.stdin.isatty():
        return [("stdin", sys.stdin.read(), None)], "stdin", doc
    raise DojoError(f"no tests for {src.name}: CPH has no samples for it in {src.parent / '.cph'}.\n"
                    f"Give input files (`dojo test {shell_path(src)} a.in`, checked against a.out) "
                    f"or pipe one in (`dojo test {shell_path(src)} < in.txt`).")


def _file_test(p: Path) -> tuple[str, str, str | None]:
    ans = None
    for suffix in ANSWER_SUFFIXES:
        q = p.with_suffix(suffix)
        if q != p and q.is_file():
            ans = _read(q)
            break
    return p.name, _read(p), ans


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise DojoError(f"can't read {p}: {e.strerror}") from None


# ---- output helpers (shared with dojo stress) ------------------------------------------

def build_noted(term: Term, src: Path, *, debug: bool = False) -> Program:
    """build() with a transient 'compiling…' line on a terminal."""
    tty = sys.stderr.isatty()
    if tty:
        sys.stderr.write(term.muted(f"compiling {src.name}…"))
        sys.stderr.flush()
    try:
        return build(src, debug=debug)
    finally:
        if tty:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()


def show_warnings(term: Term, prog: Program, limit: int = 5) -> None:
    lines = [ln for ln in prog.warnings.splitlines() if "warning:" in ln]
    if not lines:
        return
    for ln in lines[:limit]:
        term.out("  " + term.s(truncate(ln, max(40, term.width - 4)), "warn"))
    if len(lines) > limit:
        term.out(term.muted(f"  … {len(lines) - limit} more warnings"))


_STYLE = {"AC": ("good", CHECK), "WA": ("bad", CROSS), "RE": ("bad", CROSS), "TLE": ("warn", CROSS),
          "RAN": ("info", "·"), "BRUTE": ("warn", "!")}


def verdict_line(term: Term, verdict: str, label: str, seconds: float, tl: float, msg: str = "") -> str:
    style, mark = _STYLE.get(verdict, ("muted", "·"))
    t = f">{tl:g} s" if verdict == "TLE" else f"{seconds:.2f} s"
    time_style = "warn" if verdict == "TLE" or seconds > tl / 2 else "muted"
    line = f"  {term.s(mark, style)} {term.s(f'{verdict:<3}', style, 'bold')}  {label:<8} {term.s(f'{t:>7}', time_style)}"
    if msg:
        line += "  " + truncate(msg, max(30, term.width - 30))
    return line


def block(term: Term, title: str, text: str, *, limit: int = BLOCK_LINES, stderr: bool = False) -> str:
    """A labelled, indented, line-limited copy of program text."""
    lines = text.rstrip("\n").splitlines() or [""]
    width = max(20, term.width - 8)
    shown = [truncate(ln, width) for ln in lines[:limit]]
    if stderr:
        shown = [term.s(ln, "bad") if _alarming(ln) else term.muted(ln) for ln in shown]
    if not text.strip():
        shown = [term.muted("(empty)")]
    out = [f"      {term.muted(title)}"] + [f"        {ln}" for ln in shown]
    if len(lines) > limit:
        out.append("        " + term.muted(f"… {len(lines) - limit} more lines"))
    return "\n".join(out)


def _alarming(line: str) -> bool:
    return any(k in line for k in ("runtime error", "ERROR: AddressSanitizer", "Exception in thread",
                                   "terminate called", "Assertion", "Error: attempt", "Traceback"))


def shell_path(p: Path) -> str:
    """A short, shell-safe way to name `p` from the current directory."""
    p = Path(p)
    try:
        rel = os.path.relpath(p.resolve(), Path.cwd())
    except ValueError:
        rel = str(p)
    text = rel if not rel.startswith("../../") else str(p.resolve())
    return shlex.quote(text)
