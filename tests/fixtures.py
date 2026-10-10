"""Builders for offline tests: synthetic snapshots, a temporary DOJO_HOME, a captured Term.

    snap = make_snapshot(
        problems=[prob("2227B", 800, ["greedy"])],
        submissions=[sub("2227B", "WRONG_ANSWER", ts(3)), sub("2227B", "OK", ts(2))],
    )
"""
from __future__ import annotations

import datetime as dt
import io
import itertools
import os
import shutil
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from dojo.cf.model import Contest, Problem, RatingChange, Submission, split_key
from dojo.cf.snapshot import ALL, Snapshot
from dojo.config import Config
from dojo.state import State
from dojo.term import Term

CAIRO = ZoneInfo("Africa/Cairo")
# Fixed "now" for tests: Tuesday 6 Oct 2026, 12:00 Cairo time (training week began Sat 3 Oct).
NOW = dt.datetime(2026, 10, 6, 12, 0, tzinfo=CAIRO).timestamp()

_ids = itertools.count(1_000_000)


def ts(days_ago: float = 0, hour: int | None = None, now: float = NOW) -> int:
    """Epoch seconds `days_ago` days before NOW (optionally at a given local hour)."""
    t = dt.datetime.fromtimestamp(now, CAIRO) - dt.timedelta(days=days_ago)
    if hour is not None:
        t = t.replace(hour=hour, minute=0, second=0)
    return int(t.timestamp())


def prob(key: str, rating: int | None = None, tags=(), solved_count: int | None = 5000,
         name: str | None = None) -> Problem:
    cid, idx = split_key(key)
    return Problem(cid, idx, name or f"Problem {key}", rating, tuple(tags), solved_count)


def sub(key: str, verdict: str | None = "OK", t: float | None = None, ptype: str = "PRACTICE",
        rating: int | None = None, tags=(), name: str | None = None,
        lang: str = "C++23 (GCC 14-64, msys2)", id: int | None = None) -> Submission:
    cid, idx = split_key(key)
    return Submission(id or next(_ids), cid, idx, name or f"Problem {key}", int(NOW if t is None else t),
                      verdict, ptype, lang, rating=rating, tags=tuple(tags))


def contest(id: int, name: str, start: float, duration: int = 7200, phase: str = "FINISHED",
            type: str = "CF") -> Contest:
    return Contest(id, name, type, phase, duration, int(start))


def rating_change(cid: int, name: str, old: int, new: int, t: float, rank: int = 10000) -> RatingChange:
    return RatingChange(cid, name, rank, old, new, int(t))


def make_snapshot(*, problems=(), submissions=(), rating_history=(), contests=(), user=None,
                  archive=(), now: float = NOW, cfg: Config | None = None,
                  authenticated: bool = True, group_codes=None) -> Snapshot:
    snap = Snapshot(cfg=cfg or Config(), handle=(cfg or Config()).handle, now_ts=now)
    snap.problems = {p.key: p for p in problems}
    snap.submissions = sorted(submissions, key=lambda s: (s.time, s.id))
    snap.rating_history = sorted(rating_history, key=lambda r: r.time)
    snap.contests = {c.id: c for c in contests}
    snap.user = user
    snap.archive = list(archive)
    snap.group_codes = dict(group_codes or {})
    snap.authenticated = authenticated
    snap.loaded = set(ALL)
    snap.fetched_at = {d: now for d in ALL}
    return snap


class TempHome:
    """with TempHome() as home: ... — DOJO_HOME points at a fresh temp dir; restored on exit."""

    def __enter__(self) -> str:
        self.dir = tempfile.mkdtemp(prefix="dojo-test-")
        self.old = os.environ.get("DOJO_HOME")
        os.environ["DOJO_HOME"] = self.dir
        return self.dir

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("DOJO_HOME", None)
        else:
            os.environ["DOJO_HOME"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def temp_state() -> State:
    """A State backed by a fresh temp file."""
    return State(Path(tempfile.mkdtemp(prefix="dojo-state-")) / "state.json")


def capture_term(width: int = 100) -> tuple[Term, io.StringIO]:
    """A colourless Term writing into a StringIO: term, buf = capture_term(); ...; buf.getvalue()."""
    buf = io.StringIO()
    return Term(color=False, links=False, width=width, stream=buf), buf


def run_cli(argv: list[str], snap: Snapshot | None = None, inputs: list[str] | None = None,
            home: str | None = None) -> tuple[int, str, str]:
    """Run `dojo <argv>` in-process: (exit code, stdout, stderr). Nothing touches the network or
    your real files: `snap` replaces Codeforces data, `inputs` feeds input() line by line, and
    DOJO_HOME is a fresh temp dir unless you pass `home` (to keep state across calls)."""
    import contextlib
    from unittest import mock

    from dojo import cli

    out, err = io.StringIO(), io.StringIO()
    stack = contextlib.ExitStack()
    with stack:
        if home is None:
            stack.enter_context(TempHome())
        else:
            old = os.environ.get("DOJO_HOME")
            os.environ["DOJO_HOME"] = home
            stack.callback(lambda: os.environ.__setitem__("DOJO_HOME", old) if old is not None
                           else os.environ.pop("DOJO_HOME", None))
        stack.enter_context(mock.patch.dict(os.environ, {"NO_COLOR": "1", "CF_API_KEY": "", "CF_API_SECRET": ""}))
        if snap is not None:
            stack.enter_context(mock.patch("dojo.context.load_snapshot", lambda cfg, **kw: snap))
        else:
            def _no_network(*a, **kw):
                raise AssertionError("test tried to load Codeforces data without a snapshot")
            stack.enter_context(mock.patch("dojo.context.load_snapshot", _no_network))
        if inputs is not None:
            feed = iter(inputs)

            def _input(prompt=""):
                try:
                    return next(feed)
                except StopIteration:
                    raise EOFError from None
            stack.enter_context(mock.patch("builtins.input", _input))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()
