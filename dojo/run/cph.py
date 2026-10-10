"""Read the sample tests that Competitive Programming Helper (VS Code) saved for a file.

CPH keeps them in `.cph/.<file name>_<md5 of srcPath>.prob` next to the source:
JSON with name, group, url, timeLimit (ms), memoryLimit, tests [{input, output, id}], srcPath.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any


def cph_problem(src: Path) -> dict[str, Any] | None:
    """The CPH problem record for `src`, or None. Prefers the file whose srcPath is `src`; if the
    folder was moved (srcPath points elsewhere), falls back to the newest record for the same file name."""
    src = Path(src).expanduser().resolve()
    folder = src.parent / ".cph"
    if not folder.is_dir():
        return None
    candidates = sorted(folder.glob(glob.escape(f".{src.name}_") + "*.prob"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    fallback = None
    for f in candidates:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("tests"), list):
            continue
        src_path = str(doc.get("srcPath") or "")
        if src_path and _same(src_path, src):
            return doc
        if fallback is None and _base(src_path) == src.name:
            fallback = doc
    return fallback


def cph_tests(src: Path) -> list[tuple[str, str]] | None:
    """[(input, expected output), …] from CPH for `src`; None if CPH has nothing for it."""
    doc = cph_problem(src)
    if doc is None:
        return None
    tests = []
    for t in doc["tests"]:
        if isinstance(t, dict) and isinstance(t.get("input"), str):
            tests.append((t["input"], str(t.get("output") or "")))
    return tests


def cph_time_limit(doc: dict[str, Any] | None) -> float | None:
    """The problem's time limit in seconds, if CPH recorded one."""
    try:
        ms = float((doc or {}).get("timeLimit") or 0)
    except (TypeError, ValueError):
        return None
    return ms / 1000 if ms > 0 else None


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _same(path: str, src: Path) -> bool:
    try:
        return Path(path).expanduser().resolve() == src
    except (OSError, ValueError):
        return False
