"""Where dojo keeps its files.

Config  ~/.config/dojo/config.toml
Cache   ~/.cache/dojo/            Codeforces API responses, compiled binaries
Data    ~/.local/share/dojo/      state.json (plans, re-solve schedule, drill history), report.html

XDG_* variables are honoured. DOJO_HOME puts all three under one directory (tests use it).
"""
from __future__ import annotations

import os
from pathlib import Path


def _root(sub: str, xdg: str, default: str) -> Path:
    home = os.environ.get("DOJO_HOME")
    if home:
        return Path(home).expanduser() / sub
    base = os.environ.get(xdg)
    return (Path(base).expanduser() if base else Path.home() / default) / "dojo"


def config_dir() -> Path:
    return _root("config", "XDG_CONFIG_HOME", ".config")


def cache_dir() -> Path:
    return _root("cache", "XDG_CACHE_HOME", ".cache")


def data_dir() -> Path:
    return _root("data", "XDG_DATA_HOME", ".local/share")


def config_path() -> Path:
    return config_dir() / "config.toml"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
