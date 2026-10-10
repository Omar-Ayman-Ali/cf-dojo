"""What every command's run(ctx) receives."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Iterable

from dojo.cf.snapshot import ALL, Snapshot, load_snapshot
from dojo.config import Config
from dojo.state import State
from dojo.term import Term


@dataclass
class Ctx:
    args: argparse.Namespace
    cfg: Config
    term: Term
    state: State
    offline: bool = False
    refresh: bool = False
    _snap: Snapshot | None = field(default=None, repr=False)

    def snapshot(self, need: Iterable[str] = ALL) -> Snapshot:
        """Load (once per process) the Codeforces data. Fetches only what's stale.

        Asking for more datasets later reloads with the union, still hitting the network only
        for stale entries."""
        need = set(need)
        if self._snap is None or not need <= self._requested:
            self._requested = need | (self._requested if self._snap else set())
            self._snap = load_snapshot(self.cfg, need=self._requested, offline=self.offline,
                                       refresh=self.refresh, warn=self.term.warn, note=self.term.note)
        return self._snap

    _requested: set[str] = field(default_factory=set, repr=False)
