"""Configuration: ~/.config/dojo/config.toml over built-in defaults.

Configuration options with safe fallbacks.
"""
from __future__ import annotations

import datetime as dt
import os
import tomllib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dojo import paths
from dojo.errors import DojoError

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEFAULT_TOML = '''\
# dojo — personal Codeforces coach + course drills.
# Every key is optional; delete one to fall back to the built-in default.

[codeforces]
handle = "tourist"
target_rating = 1200                 # Pupil
# Signed API calls make user.status include your private-group submissions (most of your solves).
# Keys come from CF_API_KEY / CF_API_SECRET in the environment, else from this .env file.
env_file = ""
# problems.json from your solutions repo: group problem links + training names.
archive = ""
archive_url = ""

[training]
timezone = "Africa/Cairo"
week_start = "Sat"                   # the training week start; `weekly_goal` counts from this day
weekly_goal = 10                     # accepted problems per week
plan_size = 3                        # problems in `dojo today` (plus Java rep / upsolve / retry extras)
java_days = ["Sun", "Tue", "Thu"]    # days the plan adds an easy problem to solve in Java (CIS 201)
min_contest_id = 1500                # recommend problems from contest 1500 (2021) onwards
hide_tags = true                     # tags are spoilers; `dojo today --tags` shows them

[workspace]
dir = "~/codeforces"                 # where `dojo new` creates files
template = ""                        # your C++ template file; empty = built-in copy of template
editor = "code"                      # `dojo new --open` runs: <editor> <file>
cph_dirs = ["~/codeforces"]          # scanned for CPH group links

# Weekly classes. `dojo contests` flags rounds that clash with them. Add lectures the same way.
[[schedule]]
day = "Sat"
start = "12:00"
end = "14:00"
what = "OOP lab (CIS 201)"

[[schedule]]
day = "Sun"
start = "12:00"
end = "14:00"
what = "DBMS lab (CIS 205)"

[[schedule]]
day = "Mon"
start = "08:00"
end = "10:00"
what = "Discrete tutorial (BSC 201)"

[[schedule]]
day = "Wed"
start = "12:00"
end = "14:00"
what = "Statistics lab (CIS 208)"

[[schedule]]
day = "Wed"
start = "14:00"
end = "16:00"
what = "Logic Design lab (CIS 203)"
'''


def parse_day(text: str) -> int:
    """'Sat' / 'saturday' / 'SAT' -> 5 (datetime.weekday numbering, Monday = 0)."""
    t = str(text).strip()[:3].title()
    if t not in DAYS:
        raise DojoError(f"config: unknown day {text!r} (use Mon, Tue, … Sun)")
    return DAYS.index(t)


def parse_hhmm(text: str) -> dt.time:
    try:
        h, m = str(text).strip().split(":")
        return dt.time(int(h), int(m))
    except ValueError:
        raise DojoError(f"config: bad time {text!r} (use HH:MM, e.g. 14:00)") from None


@dataclass(frozen=True)
class ClassSlot:
    day: int            # 0 = Monday … 6 = Sunday
    start: dt.time
    end: dt.time
    what: str

    @property
    def day_name(self) -> str:
        return DAYS[self.day]


@dataclass
class Config:
    handle: str = "tourist"
    target_rating: int = 1200
    env_file: str = ""
    archive: str = ""
    archive_url: str = ""

    timezone: str = "Africa/Cairo"
    week_start: str = "Sat"
    weekly_goal: int = 10
    plan_size: int = 3
    java_days: list[str] = field(default_factory=lambda: ["Sun", "Tue", "Thu"])
    min_contest_id: int = 1500
    hide_tags: bool = True

    workspace: str = "~/codeforces"
    template: str = ""
    editor: str = "code"
    cph_dirs: list[str] = field(default_factory=lambda: ["~/codeforces"])

    schedule: list[ClassSlot] = field(default_factory=lambda: [
        ClassSlot(5, dt.time(12), dt.time(14), "OOP lab (CIS 201)"),
        ClassSlot(6, dt.time(12), dt.time(14), "DBMS lab (CIS 205)"),
        ClassSlot(0, dt.time(8), dt.time(10), "Discrete tutorial (BSC 201)"),
        ClassSlot(2, dt.time(12), dt.time(14), "Statistics lab (CIS 208)"),
        ClassSlot(2, dt.time(14), dt.time(16), "Logic Design lab (CIS 203)"),
    ])

    path: Path | None = None          # file this config was read from (None = built-in defaults)


    # ---- derived -------------------------------------------------------------

    @cached_property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise DojoError(f"config: unknown timezone {self.timezone!r}") from None

    @property
    def week_start_day(self) -> int:
        return parse_day(self.week_start)

    @property
    def java_weekdays(self) -> set[int]:
        return {parse_day(d) for d in self.java_days}

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()

    @property
    def archive_path(self) -> Path | None:
        return Path(self.archive).expanduser() if self.archive else None

    @property
    def cph_paths(self) -> list[Path]:
        return [Path(p).expanduser() for p in self.cph_dirs]

    def api_keys(self) -> tuple[str | None, str | None]:
        """(key, secret) from CF_API_KEY/CF_API_SECRET, else from env_file. Never logged."""
        key, secret = os.environ.get("CF_API_KEY"), os.environ.get("CF_API_SECRET")
        if key and secret:
            return key, secret
        if self.env_file:
            p = Path(self.env_file).expanduser()
            try:
                lines = p.read_text().splitlines()
            except OSError:
                lines = []
            env = {}
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().removeprefix("export ").strip()
                env[k] = v.strip().strip('"').strip("'")
            key = key or env.get("CF_API_KEY") or None
            secret = secret or env.get("CF_API_SECRET") or None
        return (key, secret) if key and secret else (None, None)


_SECTIONS = {
    "codeforces": ["handle", "target_rating", "env_file", "archive", "archive_url"],
    "training": ["timezone", "week_start", "weekly_goal", "plan_size", "java_days", "min_contest_id", "hide_tags"],
    "workspace": ["dir", "template", "editor", "cph_dirs"],
}
_RENAME = {("workspace", "dir"): "workspace"}


def load(path: Path | None = None) -> Config:
    """Read the config file if it exists; missing keys keep their defaults."""
    path = path or paths.config_path()
    cfg = Config()
    if not path.exists():
        return cfg
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise DojoError(f"{path}: {e}") from None
    cfg.path = path
    defaults = Config()
    for section, keys in _SECTIONS.items():
        table = raw.get(section, {})
        if not isinstance(table, dict):
            raise DojoError(f"{path}: [{section}] must be a table")
        for key, value in table.items():
            if key not in keys:
                raise DojoError(f"{path}: unknown key {section}.{key}")
            attr = _RENAME.get((section, key), key)
            want = type(getattr(defaults, attr))
            if want is int and isinstance(value, bool) or not isinstance(value, want):
                raise DojoError(f"{path}: {section}.{key} should be {want.__name__}, got {value!r}")
            setattr(cfg, attr, value)
    if "schedule" in raw:
        slots = []
        for i, s in enumerate(raw["schedule"]):
            try:
                slots.append(ClassSlot(parse_day(s["day"]), parse_hhmm(s["start"]), parse_hhmm(s["end"]),
                                       str(s.get("what", ""))))
            except KeyError as e:
                raise DojoError(f"{path}: schedule entry {i + 1} is missing {e}") from None
        cfg.schedule = slots
    unknown = set(raw) - set(_SECTIONS) - {"schedule"}
    if unknown:
        raise DojoError(f"{path}: unknown section(s) {', '.join(sorted(unknown))}")
    cfg.tz  # validate early
    cfg.week_start_day
    cfg.java_weekdays
    return cfg
