"""Typed views of Codeforces API objects.

A problem's key is contestId + index: "2227A", "1850A", "596491D". contestId >= 100000 means a
gym or group contest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

GYM_MIN_ID = 100000
KEY_RE = re.compile(r"^(\d+)([A-Za-z][A-Za-z0-9]*)$")

# Judged verdicts that count as a failed attempt. CE, SKIPPED, TESTING, REJECTED don't.
FAILED_VERDICTS = frozenset({
    "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "MEMORY_LIMIT_EXCEEDED", "RUNTIME_ERROR",
    "PRESENTATION_ERROR", "IDLENESS_LIMIT_EXCEEDED", "PARTIAL", "CHALLENGED", "FAILED",
    "CRASHED", "SECURITY_VIOLATED", "INPUT_PREPARATION_CRASHED",
})
CONTEST_TYPES = frozenset({"CONTESTANT", "OUT_OF_COMPETITION"})

VERDICT_SHORT = {
    "OK": "AC", "WRONG_ANSWER": "WA", "TIME_LIMIT_EXCEEDED": "TLE", "MEMORY_LIMIT_EXCEEDED": "MLE",
    "RUNTIME_ERROR": "RE", "COMPILATION_ERROR": "CE", "PRESENTATION_ERROR": "PE", "PARTIAL": "PARTIAL",
    "IDLENESS_LIMIT_EXCEEDED": "ILE", "CHALLENGED": "HACKED", "SKIPPED": "SKIPPED", "TESTING": "TESTING",
}


def make_key(contest_id: int, index: str) -> str:
    return f"{contest_id}{index}"


def split_key(key: str) -> tuple[int, str]:
    """'2227A' -> (2227, 'A'). Raises ValueError on anything else."""
    m = KEY_RE.match(key.strip())
    if not m:
        raise ValueError(f"not a problem id: {key!r} (expected e.g. 2227A)")
    return int(m.group(1)), m.group(2).upper()


def problem_url(contest_id: int, index: str, group_code: str | None = None) -> str:
    if contest_id >= GYM_MIN_ID:
        if group_code:
            return f"https://codeforces.com/group/{group_code}/contest/{contest_id}/problem/{index}"
        return f"https://codeforces.com/gym/{contest_id}/problem/{index}"
    return f"https://codeforces.com/contest/{contest_id}/problem/{index}"


def contest_url(contest_id: int, group_code: str | None = None) -> str:
    if contest_id >= GYM_MIN_ID:
        if group_code:
            return f"https://codeforces.com/group/{group_code}/contest/{contest_id}"
        return f"https://codeforces.com/gym/{contest_id}"
    return f"https://codeforces.com/contest/{contest_id}"


@dataclass(frozen=True)
class Problem:
    contest_id: int
    index: str
    name: str
    rating: int | None = None
    tags: tuple[str, ...] = ()
    solved_count: int | None = None      # problemset statistics; None outside the problemset
    type: str = "PROGRAMMING"

    @property
    def key(self) -> str:
        return make_key(self.contest_id, self.index)

    @property
    def is_gym(self) -> bool:
        return self.contest_id >= GYM_MIN_ID

    @classmethod
    def from_api(cls, p: dict[str, Any], solved_count: int | None = None) -> Problem | None:
        if "contestId" not in p:          # acmsguru problems have no contest id; dojo ignores them
            return None
        return cls(int(p["contestId"]), str(p["index"]), p.get("name", ""), p.get("rating"),
                   tuple(p.get("tags") or ()), solved_count, p.get("type", "PROGRAMMING"))


@dataclass(frozen=True)
class Submission:
    id: int
    contest_id: int
    index: str
    name: str
    time: int                       # epoch seconds
    verdict: str | None             # None while in queue
    participant_type: str           # CONTESTANT, PRACTICE, VIRTUAL, OUT_OF_COMPETITION, MANAGER
    language: str
    passed_tests: int = 0
    time_ms: int = 0
    memory: int = 0
    rating: int | None = None       # from the embedded problem object
    tags: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return make_key(self.contest_id, self.index)

    @property
    def ok(self) -> bool:
        return self.verdict == "OK"

    @property
    def failed(self) -> bool:
        return self.verdict in FAILED_VERDICTS

    @property
    def in_contest(self) -> bool:
        return self.participant_type in CONTEST_TYPES

    @property
    def is_gym(self) -> bool:
        return self.contest_id >= GYM_MIN_ID

    @classmethod
    def from_api(cls, s: dict[str, Any]) -> Submission | None:
        p = s.get("problem") or {}
        cid = p.get("contestId", s.get("contestId"))
        if cid is None:
            return None
        a = s.get("author") or {}
        return cls(int(s["id"]), int(cid), str(p.get("index", "?")), p.get("name", ""),
                   int(s.get("creationTimeSeconds", 0)), s.get("verdict"),
                   a.get("participantType", "PRACTICE"), s.get("programmingLanguage", ""),
                   int(s.get("passedTestCount") or 0), int(s.get("timeConsumedMillis") or 0),
                   int(s.get("memoryConsumedBytes") or 0), p.get("rating"), tuple(p.get("tags") or ()))


@dataclass(frozen=True)
class RatingChange:
    contest_id: int
    contest_name: str
    rank: int
    old: int
    new: int
    time: int

    @property
    def delta(self) -> int:
        return self.new - self.old

    @classmethod
    def from_api(cls, r: dict[str, Any]) -> RatingChange:
        return cls(int(r["contestId"]), r.get("contestName", ""), int(r.get("rank", 0)),
                   int(r.get("oldRating", 0)), int(r.get("newRating", 0)),
                   int(r.get("ratingUpdateTimeSeconds", 0)))


@dataclass(frozen=True)
class Contest:
    id: int
    name: str
    type: str                       # CF, IOI, ICPC
    phase: str                      # BEFORE, CODING, PENDING_SYSTEM_TEST, SYSTEM_TEST, FINISHED
    duration: int                   # seconds
    start: int | None               # epoch seconds

    @property
    def end(self) -> int | None:
        return None if self.start is None else self.start + self.duration

    @property
    def division(self) -> str | None:
        """'Div. 1', 'Div. 2', 'Div. 3', 'Div. 4', 'Div. 1 + Div. 2', 'Educational' or None."""
        n = self.name
        if "Educational" in n:
            return "Educational"
        divs = re.findall(r"Div\.?\s*(\d)", n)
        if not divs:
            return None
        uniq = sorted(set(divs))
        return " + ".join(f"Div. {d}" for d in uniq)

    @classmethod
    def from_api(cls, c: dict[str, Any]) -> Contest:
        return cls(int(c["id"]), c.get("name", ""), c.get("type", ""), c.get("phase", ""),
                   int(c.get("durationSeconds", 0)), c.get("startTimeSeconds"))


@dataclass
class ProblemState:
    """Everything the user did on one problem."""
    key: str
    submissions: list[Submission] = field(default_factory=list)   # ascending by time

    @property
    def judged(self) -> list[Submission]:
        return [s for s in self.submissions if s.ok or s.failed]

    @property
    def solved(self) -> bool:
        return any(s.ok for s in self.submissions)

    @property
    def first_ac(self) -> Submission | None:
        return next((s for s in self.submissions if s.ok), None)

    @property
    def last_ac(self) -> Submission | None:
        return next((s for s in reversed(self.submissions) if s.ok), None)

    @property
    def wrong_before_ac(self) -> int:
        """Failed judged attempts before the first AC (all failed attempts if never solved)."""
        n = 0
        for s in self.submissions:
            if s.ok:
                break
            n += s.failed
        return n

    @property
    def wrong_total(self) -> int:
        return sum(s.failed for s in self.submissions)

    @property
    def solved_in_contest(self) -> bool:
        ac = self.first_ac
        return bool(ac and ac.in_contest)

    @property
    def tried_in_contest(self) -> bool:
        return any(s.in_contest for s in self.submissions)

    @property
    def first_time(self) -> int:
        return self.submissions[0].time

    @property
    def last_time(self) -> int:
        return self.submissions[-1].time
