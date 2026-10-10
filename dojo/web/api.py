"""JSON views for the web UI. Each function takes what it needs and returns plain data.

They reuse the --json builders of the CLI commands, so the browser and the terminal show the
same numbers.
"""
from __future__ import annotations

import itertools
import random
import textwrap
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from dojo import __version__
from dojo.cf import analysis, contests, metrics, recommend
from dojo.cf.model import make_key, split_key
from dojo.cf.snapshot import Snapshot
from dojo.cf.upsolve import RESOLVE_INTERVALS, mark_resolved, retry_queue, upsolve_queue
from dojo.commands import java as java_cmd
from dojo.commands.retry import retry_rows
from dojo.commands.status import to_json as status_json
from dojo.commands.today import plan_doc
from dojo.commands.upsolve import upsolve_rows
from dojo.commands.weak import parse_band, report_doc
from dojo.drill import core
from dojo.run import cph
from dojo.errors import DojoError
from dojo.state import State
from dojo.term import RANKS

HEATMAP_DAYS = 26 * 7
SOURCE_SUFFIXES = (".cpp", ".cc", ".cxx", ".c", ".java", ".py")


def meta(snap: Snapshot, *, offline: bool, warnings: list[str]) -> dict[str, Any]:
    return {
        "version": __version__, "handle": snap.handle, "rating": snap.rating, "rank": snap.rank,
        "target": snap.cfg.target_rating, "offline": offline, "authenticated": snap.authenticated,
        "timezone": snap.cfg.timezone, "now": snap.now.isoformat(), "today": snap.today.isoformat(),
        "fetched_at": {k: int(v) for k, v in snap.fetched_at.items()},
        "loaded": sorted(snap.loaded), "warnings": warnings[-5:],
        "ranks": [{"low": low, "name": name, "color": colour} for low, name, colour in reversed(RANKS)],
    }


def status(snap: Snapshot) -> dict[str, Any]:
    snap.require("status")
    d = status_json(analysis.overview(snap))
    d["heatmap"] = [{"date": day.isoformat(), "solved": n} for day, n in metrics.daily_counts(snap, HEATMAP_DAYS)]
    return d


def today(snap: Snapshot, state: State, *, reroll: bool = False) -> dict[str, Any]:
    snap.require("status")
    plan = recommend.todays_plan(snap, state, reroll=reroll)
    return plan_doc(snap, plan, show_tags=True)


def skip(snap: Snapshot, state: State, ref: str) -> dict[str, Any]:
    snap.require("status")
    plan, old, new = recommend.skip_item(snap, state, ref)
    doc = plan_doc(snap, plan, show_tags=True)
    doc["skipped"] = old.key
    doc["replacement"] = new.key if new else None
    return doc


def weak(snap: Snapshot, *, band: str | None = None) -> dict[str, Any]:
    snap.require("status", "problemset")
    low, high = parse_band(band) if band else (None, None)
    rep = analysis.tag_report(snap, low=low, high=high)
    doc = report_doc(snap, rep, analysis.top_focus(rep.tags))
    default = analysis.tag_report(snap) if band else rep
    doc["default_band"] = [default.low, default.high]
    return doc


def upsolve(snap: Snapshot, *, all_: bool = False) -> dict[str, Any]:
    snap.require("status", "problemset")
    comfort = metrics.comfort_rating(snap)
    items = upsolve_queue(snap, comfort, uncapped=all_)
    hidden = 0 if all_ else len(upsolve_queue(snap, comfort, uncapped=True)) - len(items)
    rated = {r.contest_id: r for r in snap.rating_history}
    rows = upsolve_rows(snap, items)
    for row in rows:
        r = rated.get(row["contest_id"])
        row["contest_url"] = snap.contest_url(row["contest_id"])
        row["delta"] = r.delta if r else None
        row["rank"] = r.rank if r else None
        row["rating_after"] = r.new if r else None
    return {"comfort": comfort, "items": rows, "hidden": hidden}


def retry(snap: Snapshot, state: State) -> dict[str, Any]:
    snap.require("status")
    queue = retry_queue(snap, state, today=snap.today)
    due = [r for r in queue if r.kind == "resolve" and r.is_due(snap.today)]
    later = [r for r in queue if r.kind == "resolve" and not r.is_due(snap.today)]
    unsolved = [r for r in queue if r.kind == "unsolved"]
    return {"due": retry_rows(snap, due), "unsolved": retry_rows(snap, unsolved),
            "later": retry_rows(snap, later), "stages": len(RESOLVE_INTERVALS)}


def retry_done(snap: Snapshot, state: State, ref: str) -> dict[str, Any]:
    try:
        key = make_key(*split_key(ref))
    except ValueError as e:
        raise DojoError(str(e)) from None
    nxt = mark_resolved(snap, state, key, today=snap.today)
    return {"key": key, "next_due": nxt.due if nxt else None, "stage": nxt.stage if nxt else None,
            "stages": len(RESOLVE_INTERVALS)}


def upcoming(snap: Snapshot, *, days: int = 30) -> list[dict[str, Any]]:
    snap.require("contests")
    return [dict(u.to_json(), div1_only=u.div1_only) for u in contests.upcoming(snap, days=days)]


def ics(snap: Snapshot, *, days: int = 30, all_: bool = False, ids: set[int] | None = None,
        recommended: bool = False) -> str:
    """Upcoming rounds as a calendar: all of them, only `ids`, or only the ones that suit you."""
    snap.require("contests")
    items = [u for u in contests.upcoming(snap, days=days) if all_ or ids or not u.div1_only]
    if ids:
        items = [u for u in items if u.contest.id in ids]
    if recommended:
        items = [u for u in items if u.recommended]
    return contests.to_ics(items, snap.now)


# ---- drills ----------------------------------------------------------------------------------

def drill_topics(state: State) -> dict[str, Any]:
    topics = core.load_topics()
    st = core.stats(state)
    rows = []
    for t in topics.values():
        s = st.get(t.key)
        rows.append({"key": t.key, "title": t.title, "course": t.course, "summary": t.summary,
                     "levels": t.levels, "solve_usage": t.solve_usage,
                     "attempts": s.attempts if s else 0, "correct": s.correct if s else 0,
                     "recent_accuracy": s.recent_accuracy if s else None,
                     "last_ts": s.last_ts if s else None})
    pick = core.suggest(state)
    return {"courses": core.COURSES, "topics": rows,
            "suggest": {"key": pick[0].key, "why": pick[1]} if pick else None}


class DrillSessions:
    """Questions handed to the browser, kept until answered. The checker is a closure, so the
    question has to stay server-side; the browser only gets an id."""

    LIMIT = 200

    def __init__(self) -> None:
        self._q: OrderedDict[str, tuple[core.Topic, int, core.Question, float]] = OrderedDict()
        self._ids = itertools.count(1)

    def next(self, keys: list[str], level: int, seed: int) -> dict[str, Any]:
        topics = core.load_topics()
        chosen = [topics[k] for k in keys if k in topics] or list(topics.values())
        rng = random.Random(seed)
        topic = chosen[rng.randrange(len(chosen))]
        lvl = max(1, min(level, topic.levels))
        q = topic.generate(rng, lvl)
        qid = f"q{next(self._ids)}-{seed}"
        self._q[qid] = (topic, lvl, q, time.monotonic())
        while len(self._q) > self.LIMIT:
            self._q.popitem(last=False)
        return {"id": qid, "topic": topic.key, "title": topic.title, "course": topic.course,
                "level": lvl, "levels": topic.levels, "prompt": q.prompt, "expect": q.expect,
                "has_hint": bool(q.hint)}

    def answer(self, state: State, qid: str, text: str) -> dict[str, Any]:
        if qid not in self._q:
            raise DojoError("that question has expired — get a new one")
        topic, lvl, q, start = self._q[qid]
        text = text.strip()
        if text == "?":
            return {"kind": "hint", "hint": q.hint or "No hint for this one. Reveal shows the worked solution."}
        if text == "!":
            v = core.Verdict(False, "revealed")
        else:
            if not text:
                raise DojoError("type an answer first")
            try:
                v = q.check(text)
            except Exception as e:            # a checker bug must not break the page
                v = core.Verdict(False, f"couldn't check that ({e.__class__.__name__}: {e})", retry=True)
            if v.retry:
                return {"kind": "retry", "message": v.message or "couldn't read that", "expect": q.expect}
        del self._q[qid]
        core.record(state, topic.key, v.ok, lvl, time.monotonic() - start)
        return {"kind": "verdict", "ok": v.ok, "revealed": text == "!",
                "message": "" if v.message == "revealed" else v.message,
                "answer": q.answer, "solution": q.solution}


def solve(topic_key: str, text: str, check: str | None) -> dict[str, Any]:
    topics = core.load_topics()
    t = topics.get(topic_key)
    if not t:
        raise DojoError(f"unknown topic {topic_key!r}")
    if not text.strip():
        raise DojoError(f"type a problem, e.g. {t.solve_usage}")
    try:
        q = t.solve(text.strip())
    except ValueError as e:
        raise DojoError(f"{e} — format: {t.solve_usage}") from None
    out: dict[str, Any] = {"prompt": q.prompt, "answer": q.answer, "solution": q.solution, "hint": q.hint}
    if check and check.strip():
        v = q.check(check)
        out["verdict"] = {"ok": v.ok, "retry": v.retry, "message": v.message, "expect": q.expect}
    return out


# ---- java + files ----------------------------------------------------------------------------

def java_sheet() -> list[dict[str, Any]]:
    out = []
    for sec in java_cmd.SECTIONS:
        blocks = []
        for b in sec.blocks:
            if isinstance(b, str):
                blocks.append({"type": "text", "text": b})
            elif isinstance(b, java_cmd.Table):
                blocks.append({"type": "table", "header": b.header, "rows": b.rows})
            else:
                blocks.append({"type": "code", "code": textwrap.dedent(b.code).strip("\n"),
                               "stdin": b.stdin, "expect": b.expect})
        out.append({"key": sec.key, "title": sec.title, "blocks": blocks})
    return out


def recent_files(root: Path, limit: int = 40) -> list[dict[str, Any]]:
    """Newest solution files under the workspace (two levels deep), for the judge's file picker."""
    found: list[tuple[float, Path]] = []
    if not root.is_dir():
        return []
    for pattern in ("*", "*/*"):
        for p in root.glob(pattern):
            if p.suffix in SOURCE_SUFFIXES and p.is_file() and not any(part.startswith(".") for part in p.parts):
                try:
                    found.append((p.stat().st_mtime, p))
                except OSError:
                    pass
    found.sort(reverse=True)
    return [{"path": str(p), "name": p.name, "mtime": int(m), "samples": len(cph.cph_tests(p) or [])}
            for m, p in found[:limit]]
