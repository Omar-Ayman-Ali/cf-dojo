"""Disk cache for API responses: ~/.cache/dojo/<name>.json.gz = {"fetched_at": ts, "data": ...}."""
from __future__ import annotations

import gzip
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / f"{name}.json.gz"

    def load(self, name: str) -> tuple[Any, float] | None:
        """(data, fetched_at) or None if missing/unreadable."""
        try:
            with gzip.open(self.path(name), "rt", encoding="utf-8") as f:
                doc = json.load(f)
            return doc["data"], float(doc["fetched_at"])
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            return None

    def save(self, name: str, data: Any, fetched_at: float | None = None) -> float:
        fetched_at = time.time() if fetched_at is None else fetched_at
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=f".{name}.", suffix=".tmp")
        with os.fdopen(fd, "wb") as raw, gzip.open(raw, "wt", encoding="utf-8") as f:
            json.dump({"fetched_at": fetched_at, "data": data}, f, separators=(",", ":"))
        os.replace(tmp, self.path(name))
        return fetched_at
