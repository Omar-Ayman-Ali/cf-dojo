"""Run a built program on one input and judge its output.

    res = run(prog, "3\\n1 2 3\\n", tl=2.0)
    ok, why = compare(res.stdout, "6\\n")                       # (False, "line 1, token 1: expected 6, got 5")
    verdict, why = judge(res, "6\\n", tl=2.0)                   # ("WA", "line 1, token 1: …")

Programs run in their own process group (killed whole on timeout or Ctrl-C), with the stack
limit raised like on Codeforces so deep recursion doesn't crash locally only.
"""
from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from dojo.errors import DojoError
from dojo.run.lang import Program

OUTPUT_LIMIT = 64 << 20          # bytes of stdout kept before the run is killed
STDERR_LIMIT = 1 << 20
STACK_BYTES = 256 << 20          # Codeforces gives the stack the whole memory limit

SIGNAL_HINTS = {
    "SIGSEGV": "invalid memory access: index out of range, null pointer or stack overflow",
    "SIGFPE": "arithmetic error: division or modulo by zero",
    "SIGABRT": "aborted: failed assert, uncaught exception or bad_alloc",
    "SIGBUS": "invalid memory access",
    "SIGKILL": "killed",
}


@dataclass
class RunResult:
    stdout: str
    stderr: str
    code: int
    seconds: float
    timed_out: bool
    signal: str | None                  # "SIGSEGV", … when killed by a signal
    output_limit: bool = False          # killed for printing more than OUTPUT_LIMIT

    @property
    def crashed(self) -> bool:
        return not self.timed_out and (self.code != 0 or self.output_limit)

    def describe(self) -> str:
        """Why the run failed, in a few words ('' if it didn't)."""
        if self.timed_out:
            return "time limit exceeded"
        if self.output_limit:
            return f"printed more than {OUTPUT_LIMIT >> 20} MB — killed"
        if self.signal:
            hint = SIGNAL_HINTS.get(self.signal)
            return f"{self.signal}" + (f" ({hint})" if hint else "")
        if self.code != 0:
            exc = _java_exception(self.stderr)
            return f"exit code {self.code}" + (f" ({exc})" if exc else "")
        return ""


def _raise_stack() -> None:
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
        want = STACK_BYTES if hard == resource.RLIM_INFINITY else min(STACK_BYTES, hard)
        if soft != resource.RLIM_INFINITY and soft < want:
            resource.setrlimit(resource.RLIMIT_STACK, (want, hard))
    except (ImportError, ValueError, OSError):
        pass


def run(prog: Program, stdin: str, *, tl: float = 2.0, args: Sequence[str] = ()) -> RunResult:
    """Run `prog` with `stdin`; kill it (and its children) after `tl` seconds of wall time."""
    env = {**os.environ, **prog.env} if prog.env else None
    argv = [*prog.cmd(), *map(str, args)]
    t0 = time.perf_counter()
    try:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=prog.src.parent, env=env, start_new_session=True,
                             preexec_fn=_raise_stack if os.name == "posix" else None)
    except OSError as e:
        raise DojoError(f"couldn't start {prog.name}: {e.strerror or e}") from None

    out: list[bytes] = []
    err: list[bytes] = []
    over = threading.Event()

    def feed():
        try:
            if stdin:
                p.stdin.write(stdin.encode())
        except (BrokenPipeError, OSError):
            pass                         # the program stopped reading early; that's allowed
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass

    def drain(stream, sink: list[bytes], limit: int, is_stdout: bool):
        size = 0
        while True:
            chunk = stream.read1(1 << 16) if hasattr(stream, "read1") else stream.read(1 << 16)
            if not chunk:
                break
            if size < limit:
                sink.append(chunk[:limit - size])
            size += len(chunk)
            if is_stdout and size > limit and not over.is_set():
                over.set()
                _kill(p)

    threads = [threading.Thread(target=feed, daemon=True),
               threading.Thread(target=drain, args=(p.stdout, out, OUTPUT_LIMIT, True), daemon=True),
               threading.Thread(target=drain, args=(p.stderr, err, STDERR_LIMIT, False), daemon=True)]
    for t in threads:
        t.start()
    timed_out = False
    try:
        try:
            p.wait(timeout=tl)
        except subprocess.TimeoutExpired:
            timed_out = True
        seconds = time.perf_counter() - t0
    finally:
        _kill(p)                       # on timeout or Ctrl-C, and stray children holding the pipes
        p.wait()
    for t in threads:
        t.join(timeout=5)
    for f in (p.stdout, p.stderr):
        try:
            f.close()
        except OSError:
            pass
    code = p.returncode
    sig = None
    if code is not None and code < 0:
        try:
            sig = signal.Signals(-code).name
        except ValueError:
            sig = f"signal {-code}"
    return RunResult(stdout=b"".join(out).decode("utf-8", "replace"),
                     stderr=b"".join(err).decode("utf-8", "replace"),
                     code=code if code is not None else -9, seconds=min(seconds, tl) if timed_out else seconds,
                     timed_out=timed_out, signal=None if timed_out else sig,
                     output_limit=over.is_set() and not timed_out)


def _kill(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _java_exception(stderr: str) -> str:
    m = re.search(r"Exception in thread \"[^\"]*\" ([\w.$]+(?::[^\n]*)?)", stderr)
    if not m:
        return ""
    return m.group(1).removeprefix("java.lang.").strip()[:80]


# ---- comparing -------------------------------------------------------------------------

_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _tokens(text: str) -> list[tuple[str, int]]:
    """Whitespace-separated tokens with their 1-based line numbers."""
    return [(tok, n) for n, line in enumerate(text.splitlines(), 1) for tok in line.split()]


def _show(tok: str, limit: int = 40) -> str:
    return tok if len(tok) <= limit else tok[:limit - 1] + "…"


def compare(out: str, ans: str, *, mode: str = "tokens", eps: float = 1e-6) -> tuple[bool, str]:
    """Compare output to the expected answer. Modes:
      tokens  whitespace-insensitive (what most Codeforces checkers do)
      exact   line by line; trailing spaces and trailing blank lines ignored
      float   like tokens, but numbers match within `eps` absolute or relative error
    Returns (ok, message): the message points at the first difference ('' when ok)."""
    if mode == "exact":
        return _compare_exact(out, ans)
    if mode not in ("tokens", "float"):
        raise ValueError(f"unknown compare mode {mode!r}")
    got, exp = _tokens(out), _tokens(ans)
    for i, ((g, gl), (e, el)) in enumerate(zip(got, exp), 1):
        if g == e:
            continue
        if mode == "float" and _NUMBER.fullmatch(g) and _NUMBER.fullmatch(e):
            a, b = float(g), float(e)
            diff = abs(a - b)
            if diff <= eps or diff <= eps * abs(b) or (math.isinf(a) and a == b):
                continue
            return False, f"line {gl}, token {i}: expected {_show(e)}, got {_show(g)} (off by {diff:.3g}, allowed {eps:g})"
        msg = f"line {gl}, token {i}: expected {_show(e)}, got {_show(g)}"
        if g.lower() == e.lower():
            msg += " (differs only in letter case)"
        return False, msg
    if len(got) < len(exp):
        e, el = exp[len(got)]
        if not got:
            return False, f"no output (expected {_show(e)} first)"
        return False, f"output ends early: {len(got)} of {len(exp)} tokens; next expected {_show(e)} on line {el}"
    if len(got) > len(exp):
        g, gl = got[len(exp)]
        return False, f"extra output: {_show(g)} on line {gl} after all {len(exp)} expected tokens"
    return True, ""


def _compare_exact(out: str, ans: str) -> tuple[bool, str]:
    a = [ln.rstrip() for ln in out.splitlines()]
    b = [ln.rstrip() for ln in ans.splitlines()]
    while a and not a[-1]:
        a.pop()
    while b and not b[-1]:
        b.pop()
    for n, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            return False, f"line {n}: expected {_show(y, 60)!r}, got {_show(x, 60)!r}"
    if len(a) < len(b):
        return False, f"output ends early: {len(a)} of {len(b)} lines; line {len(a) + 1} should be {_show(b[len(a)], 60)!r}"
    if len(a) > len(b):
        return False, f"extra output on line {len(b) + 1}: {_show(a[len(b)], 60)!r}"
    return True, ""


# ---- verdicts --------------------------------------------------------------------------

def check(checker: Program, stdin: str, out: str, ans: str, *, tl: float = 10.0) -> tuple[bool, str]:
    """Run a testlib-style checker: `checker input output answer`; exit code 0 = accepted."""
    with tempfile.TemporaryDirectory(prefix="dojo-check-") as d:
        files = []
        for name, text in (("input.txt", stdin), ("output.txt", out), ("answer.txt", ans)):
            path = Path(d) / name
            path.write_text(text)
            files.append(str(path))
        res = run(checker, "", tl=tl, args=files)
    if res.timed_out:
        raise DojoError(f"checker {checker.name} took over {tl:g} s")
    if res.code == 0:
        return True, ""
    said = (res.stderr.strip() or res.stdout.strip()).splitlines()
    return False, "checker: " + (said[0][:160] if said else f"rejected (exit code {res.code})")


def judge(res: RunResult, ans: str | None, *, mode: str = "tokens", eps: float = 1e-6,
          checker: Program | None = None, stdin: str = "") -> tuple[str, str]:
    """Verdict for one run: ("AC" | "WA" | "TLE" | "RE" | "RAN", message).
    "RAN" means it finished cleanly but there was no answer to compare against."""
    if res.timed_out:
        return "TLE", ""
    if res.crashed:
        return "RE", res.describe()
    if ans is None:
        return "RAN", ""
    if checker is not None:
        ok, msg = check(checker, stdin, res.stdout, ans)
    else:
        ok, msg = compare(res.stdout, ans, mode=mode, eps=eps)
    return ("AC", "") if ok else ("WA", msg)
