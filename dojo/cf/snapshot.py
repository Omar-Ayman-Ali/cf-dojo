"""Everything dojo knows about the user, loaded from cache or the API.

    snap = load_snapshot(cfg, offline=False)
    snap.rating, snap.submissions, snap.problems, snap.states["2227B"].wrong_before_ac

Datasets and how long a cached copy counts as fresh:
    user        user.info              30 min
    rating      user.rating            30 min
    status      user.status (signed)    5 min   — short, so `dojo today` ticks a solve quickly
    problemset  problemset.problems    24 h
    contests    contest.list            3 h
    archive     solutions problems.json — local file if present, else GitHub raw (6 h)
A failed fetch falls back to the cached copy with a warning; no copy at all is a DojoError.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from dojo import paths
from dojo.cf.api import CFClient, CFError, http_get
from dojo.cf.cache import Cache
from dojo.cf.model import (GYM_MIN_ID, Contest, Problem, ProblemState, RatingChange, Submission,
                           contest_url, make_key, problem_url, split_key)
from dojo.config import Config
from dojo.errors import DojoError

ALL = ("user", "rating", "status", "problemset", "contests", "archive")
TTL = {"user": 1800, "rating": 1800, "status": 300, "problemset": 86400, "contests": 3 * 3600,
       "archive": 6 * 3600}


@dataclass
class Snapshot:
    cfg: Config
    handle: str
    user: dict[str, Any] | None = None
    rating_history: list[RatingChange] = field(default_factory=list)
    submissions: list[Submission] = field(default_factory=list)       # ascending by time
    problems: dict[str, Problem] = field(default_factory=dict)        # problemset, by key
    contests: dict[int, Contest] = field(default_factory=dict)
    archive: list[dict[str, Any]] = field(default_factory=list)       # solutions repo problems.json
    group_codes: dict[int, str] = field(default_factory=dict)         # contestId -> group code
    group_names: dict[int, str] = field(default_factory=dict)         # contestId -> CPH sheet name
    authenticated: bool = False          # submissions include private-group ones
    fetched_at: dict[str, float] = field(default_factory=dict)
    loaded: set[str] = field(default_factory=set)                     # datasets actually available
    now_ts: float = field(default_factory=time.time)                  # injectable for tests

    # ---- basics --------------------------------------------------------------------

    @property
    def tz(self) -> ZoneInfo:
        return self.cfg.tz

    @property
    def now(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.now_ts, self.tz)

    @property
    def today(self) -> dt.date:
        return self.now.date()

    def local_date(self, ts: float) -> dt.date:
        return dt.datetime.fromtimestamp(ts, self.tz).date()

    @property
    def rating(self) -> int | None:
        if self.user and "rating" in self.user:
            return int(self.user["rating"])
        return self.rating_history[-1].new if self.rating_history else None

    @property
    def max_rating(self) -> int | None:
        if self.user and "maxRating" in self.user:
            return int(self.user["maxRating"])
        return max((r.new for r in self.rating_history), default=None)

    @property
    def rank(self) -> str:
        """Codeforces rank name ('newbie', 'pupil', …); derived from the rating without user.info."""
        if self.user and self.user.get("rank"):
            return str(self.user["rank"])
        from dojo.term import rank_of
        return rank_of(self.rating)[0]

    # ---- derived indexes -----------------------------------------------------------

    @cached_property
    def states(self) -> dict[str, ProblemState]:
        out: dict[str, ProblemState] = {}
        for s in self.submissions:
            out.setdefault(s.key, ProblemState(s.key)).submissions.append(s)
        return out

    @cached_property
    def solved(self) -> set[str]:
        return {k for k, st in self.states.items() if st.solved}

    @cached_property
    def attempted_unsolved(self) -> set[str]:
        return {k for k, st in self.states.items() if not st.solved and st.wrong_total > 0}

    @cached_property
    def archive_by_key(self) -> dict[str, dict[str, Any]]:
        out = {}
        for a in self.archive:
            try:
                out[make_key(int(a["contestId"]), str(a["index"]))] = a
            except (KeyError, ValueError, TypeError):
                continue
        return out

    @cached_property
    def archive_solved(self) -> set[str]:
        """Solves known only from the solutions archive (private groups, when unsigned)."""
        return set(self.archive_by_key)

    @cached_property
    def all_solved(self) -> set[str]:
        return self.solved | self.archive_solved

    @cached_property
    def ac_times(self) -> list[int]:
        """Time of every first AC per problem, ascending (one entry per solved problem)."""
        return sorted(st.first_ac.time for st in self.states.values() if st.first_ac)

    @cached_property
    def ac_days(self) -> list[dt.date]:
        """Sorted unique local dates with at least one accepted submission."""
        return sorted({self.local_date(s.time) for s in self.submissions if s.ok})

    def training_name(self, contest_id: int) -> str | None:
        """Group and training name from the archive's folder names."""
        for a in self.archive:
            if a.get("contestId") == contest_id:
                top = str(a.get("relativeFolder", "")).split("/")[0]
                if top and not top.startswith("contest-") and not top.startswith("Rating-"):
                    return top
        return None

    # ---- lookups -------------------------------------------------------------------

    def problem(self, key: str) -> Problem:
        """Problemset entry, else rebuilt from the user's submissions or the archive."""
        if key in self.problems:
            return self.problems[key]
        st = self.states.get(key)
        if st:
            s = st.submissions[-1]
            return Problem(s.contest_id, s.index, s.name, s.rating, s.tags)
        a = self.archive_by_key.get(key)
        if a:
            tags = tuple(t for t in a.get("tags") or () if t != "untagged")
            return Problem(int(a["contestId"]), str(a["index"]), a.get("name", ""), a.get("rating"), tags)
        cid, idx = split_key(key)
        return Problem(cid, idx, "")

    def url(self, key: str) -> str:
        a = self.archive_by_key.get(key)
        if a and a.get("url"):
            return a["url"]
        cid, idx = split_key(key)
        return problem_url(cid, idx, self.group_codes.get(cid))

    def contest_url(self, contest_id: int) -> str:
        return contest_url(contest_id, self.group_codes.get(contest_id))

    def contest_name(self, contest_id: int) -> str:
        c = self.contests.get(contest_id)
        if c:
            return c.name
        for r in self.rating_history:
            if r.contest_id == contest_id:
                return r.contest_name
        return (self.group_names.get(contest_id) or self.training_name(contest_id)
                or (f"Gym/group {contest_id}" if contest_id >= GYM_MIN_ID else f"Contest {contest_id}"))

    def solved_between(self, start_ts: float, end_ts: float) -> list[str]:
        """Keys whose first AC falls in [start, end)."""
        return [k for k, st in self.states.items()
                if st.first_ac and start_ts <= st.first_ac.time < end_ts]

    def require(self, *datasets: str) -> None:
        missing = [d for d in datasets if d not in self.loaded]
        if missing:
            raise DojoError(f"no {', '.join(missing)} data yet — run `dojo sync` while online")


# ---- loading ---------------------------------------------------------------------------

def load_snapshot(cfg: Config, *, need: Iterable[str] = ALL, offline: bool = False,
                  refresh: bool = False, warn: Callable[[str], None] | None = None,
                  note: Callable[[str], None] | None = None, client: CFClient | None = None,
                  cache: Cache | None = None, now: float | None = None) -> Snapshot:
    """Build a Snapshot from fresh cache entries, fetching stale ones unless offline.

    Missing datasets are left out of snap.loaded (commands call snap.require(...)).
    """
    warn = warn or (lambda m: None)
    note = note or (lambda m: None)
    cache = cache or Cache(paths.cache_dir())
    now = time.time() if now is None else now
    key, secret = cfg.api_keys()
    client = client or CFClient(key, secret, lock_dir=cache.root)
    snap = Snapshot(cfg=cfg, handle=cfg.handle, now_ts=now)
    need = [d for d in ALL if d in set(need)]

    for name in need:
        if name == "archive":
            _load_archive(snap, cfg, cache, offline, refresh, now, warn)
            continue
        signed = name == "status" and client.can_sign
        cname = f"{name}.{cfg.handle}" if name in ("user", "rating", "status") else name
        if signed:
            cname += ".signed"
        hit = cache.load(cname)
        if hit is None and name == "status" and signed and offline:
            hit = cache.load(f"status.{cfg.handle}")       # offline: public copy beats nothing
            signed = hit is None
        stale = hit is None or now - hit[1] >= TTL[name]
        data, at = hit if hit else (None, None)
        if not offline and (refresh or stale):
            try:
                note(f"fetching {name}…")
                data = _fetch(client, name, cfg.handle, signed)
                at = cache.save(cname, data)
            except CFError as e:
                if hit:
                    data, at = hit
                    warn(f"{e}; using cached {name} from {_age(now - at)} ago")
                elif signed:
                    # A broken key shouldn't block everything: fall back to public data.
                    warn(f"signed user.status failed ({e}); using public submissions only")
                    try:
                        data = _fetch(client, name, cfg.handle, False)
                        at = cache.save(f"status.{cfg.handle}", data)
                        signed = False
                    except CFError as e2:
                        warn(str(e2))
                else:
                    warn(str(e))
        if data is None:
            continue
        _apply(snap, name, data)
        snap.fetched_at[name] = at
        snap.loaded.add(name)
        if name == "status":
            snap.authenticated = signed
    codes, names = _scan_cph(cfg)
    snap.group_codes.update(codes)
    snap.group_names.update(names)
    for a in snap.archive:
        url = str(a.get("url", ""))
        if "/group/" in url:
            try:
                snap.group_codes.setdefault(int(a["contestId"]), url.split("/group/")[1].split("/")[0])
            except (KeyError, ValueError, IndexError):
                pass
    return snap


def _fetch(client: CFClient, name: str, handle: str, signed: bool) -> Any:
    if name == "user":
        return client.call("user.info", {"handles": handle})[0]
    if name == "rating":
        return client.call("user.rating", {"handle": handle})
    if name == "status":
        return client.call("user.status", {"handle": handle}, signed=signed)
    if name == "problemset":
        return client.call("problemset.problems")
    if name == "contests":
        return client.call("contest.list", {"gym": False})
    raise ValueError(name)


def _apply(snap: Snapshot, name: str, data: Any) -> None:
    if name == "user":
        snap.user = data
    elif name == "rating":
        snap.rating_history = sorted((RatingChange.from_api(r) for r in data), key=lambda r: r.time)
    elif name == "status":
        subs = (Submission.from_api(s) for s in data)
        snap.submissions = sorted((s for s in subs if s), key=lambda s: (s.time, s.id))
    elif name == "problemset":
        counts = {make_key(int(st["contestId"]), st["index"]): st.get("solvedCount")
                  for st in data.get("problemStatistics", []) if "contestId" in st}
        for p in data.get("problems", []):
            prob = Problem.from_api(p)
            if prob:
                snap.problems[prob.key] = Problem(prob.contest_id, prob.index, prob.name, prob.rating,
                                                  prob.tags, counts.get(prob.key), prob.type)
    elif name == "contests":
        snap.contests = {c.id: c for c in (Contest.from_api(x) for x in data)}


def _load_archive(snap: Snapshot, cfg: Config, cache: Cache, offline: bool, refresh: bool,
                  now: float, warn: Callable[[str], None]) -> None:
    """The GitHub copy is the one cf_sync keeps current; the local clone is the offline fallback."""
    hit = cache.load("archive") if cfg.archive_url else None
    data, at = hit if hit else (None, None)
    if cfg.archive_url and not offline and (refresh or hit is None or now - hit[1] >= TTL["archive"]):
        try:
            status, body = http_get(cfg.archive_url, timeout=30)
            if status != 200:
                raise CFError(f"HTTP {status}")
            data = _archive_list(json.loads(body))
            at = cache.save("archive", data)
        except (CFError, ValueError):
            pass                                    # stale cache or the local clone will do
    path = cfg.archive_path
    if data is None and path and path.exists():
        try:
            data, at = _archive_list(json.loads(path.read_text())), path.stat().st_mtime
        except (OSError, ValueError) as e:
            warn(f"can't read {path}: {e}")
    if data is not None:
        snap.archive = data
        snap.fetched_at["archive"] = at
        snap.loaded.add("archive")


def _archive_list(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, dict):
        doc = doc.get("problems") or doc.get("solved") or []
    return [a for a in doc if isinstance(a, dict)] if isinstance(doc, list) else []


def _scan_cph(cfg: Config) -> tuple[dict[int, str], dict[int, str]]:
    """From Competitive Programming Helper's .cph/*.prob files: contestId -> group code, and
    contestId -> the sheet name Competitive Companion recorded ("Sheet Three || Time Complexity…")."""
    codes: dict[int, str] = {}
    names: dict[int, str] = {}
    for d in cfg.cph_paths:
        cph = d / ".cph"
        if not cph.is_dir():
            continue
        for f in cph.glob("*.prob"):
            try:
                doc = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            url = str(doc.get("url", ""))
            if "/contest/" not in url:
                continue
            try:
                cid = int(url.split("/contest/")[1].split("/")[0])
            except (IndexError, ValueError):
                continue
            if "/group/" in url:
                codes.setdefault(cid, url.split("/group/")[1].split("/")[0])
            group = str(doc.get("group", "")).removeprefix("Codeforces - ").strip()
            if group and cid >= GYM_MIN_ID:
                names.setdefault(cid, group)
    return codes, names


def _age(seconds: float) -> str:
    from dojo.timeutil import fmt_duration
    return fmt_duration(seconds)
