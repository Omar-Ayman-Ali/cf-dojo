"""Persistent state: one JSON document, ~/.local/share/dojo/state.json.

Top-level keys are sections, each owned by one feature:
  plans    {"YYYY-MM-DD": plan}            dojo today
  resolve  {problem_key: schedule}         dojo retry (spaced re-solve)
  drill    [result, ...]                   dojo drill history

save() rewrites only the sections this process touched, under a file lock, so two dojo
processes (say `dojo bar` from the status bar and `dojo today` in a terminal) can't clobber
each other's sections.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from dojo import paths


class State:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.data_dir() / "state.json"
        self._doc: dict[str, Any] | None = None
        self._dirty: set[str] = set()

    def _load(self) -> dict[str, Any]:
        if self._doc is None:
            self._doc = _read(self.path)
        return self._doc

    def get(self, section: str, default: Any = None) -> Any:
        """The section's value (a live object: mutate it, then call touch(section))."""
        doc = self._load()
        if section not in doc:
            if default is None:
                return None
            doc[section] = copy.deepcopy(default)
        return doc[section]

    def set(self, section: str, value: Any) -> None:
        self._load()[section] = value
        self._dirty.add(section)

    def touch(self, section: str) -> None:
        """Mark a section changed after mutating the object get() returned."""
        self._load()
        self._dirty.add(section)

    def save(self) -> None:
        if not self._dirty or self._doc is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(".lock")
        with open(lock, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            current = _read(self.path)
            for section in self._dirty:
                if section in self._doc:
                    current[section] = self._doc[section]
                else:
                    current.pop(section, None)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state.", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(current, f, indent=1, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, self.path)
        self._dirty.clear()


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # A corrupt state file shouldn't brick the tool: keep it for inspection, start fresh.
        try:
            path.replace(path.with_suffix(".corrupt.json"))
        except OSError:
            pass
        return {}
    return doc if isinstance(doc, dict) else {}
