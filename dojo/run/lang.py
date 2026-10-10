"""Turn a source file into something runnable: C++, C, Java or Python.

    prog = build(Path("A_Koshary.cpp"))            # g++ -std=c++23 -O2 … (cached)
    prog.cmd()                                      # ['/home/…/.cache/dojo/build/3f…/prog']

Compiled programs live in cache_dir()/build/<hash>/, keyed by the source, the source of any
`#include "local.h"` next to it, the flags and the compiler version — so an unchanged file is
never compiled twice, across directories and runs.
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dojo import paths
from dojo.errors import DojoError

LANGS = {".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c++": "cpp", ".c": "c", ".java": "java", ".py": "py"}
# Preference when several files share a stem (brute.cpp and brute.py): the first one wins.
LANG_ORDER = ("cpp", "c", "java", "py")

CXX_FLAGS = ["-O2", "-Wall", "-Wextra", "-Wshadow", "-DLOCAL"]
C_FLAGS = ["-std=c17", "-O2", "-Wall", "-Wextra", "-Wshadow", "-DLOCAL"]
DEBUG_FLAGS = ["-g", "-fsanitize=address,undefined", "-D_GLIBCXX_DEBUG"]
# Leak reports would turn every solution that never frees memory (most of them) into a runtime error.
DEBUG_ENV = {"ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "print_stacktrace=1"}
JAVA_FLAGS = ["-Xss64m", "-XX:+UseSerialGC"]

COMPILE_TIMEOUT = 120
ERROR_LINES = 30
KEEP_BUILDS = 300


@dataclass
class Program:
    src: Path
    lang: str                                   # "cpp" | "c" | "java" | "py"
    exe: Path | None = None                     # cpp / c binary
    classpath: Path | None = None               # java: directory with the .class files
    main_class: str | None = None               # java
    env: dict[str, str] = field(default_factory=dict)   # extra environment for runs
    warnings: str = ""                          # compiler warnings (kept with cached builds too)
    debug: bool = False
    cached: bool = False                        # True when no compile was needed

    def cmd(self) -> list[str]:
        """argv to run the program (after build)."""
        if self.lang in ("cpp", "c"):
            return [str(self.exe)]
        if self.lang == "java":
            return [_java(), *JAVA_FLAGS, "-cp", str(self.classpath), self.main_class or "Main"]
        if self.lang == "py":
            return [sys.executable, str(self.src)]
        raise DojoError(f"don't know how to run {self.lang} programs")

    @property
    def name(self) -> str:
        return self.src.name


def lang_of(src: Path) -> str:
    lang = LANGS.get(src.suffix.lower())
    if lang is None:
        raise DojoError(f"can't run {src.name} — dojo runs C++ (.cpp), C (.c), Java (.java) and Python (.py)")
    return lang


def build(src: Path, *, debug: bool = False, std: str = "c++23") -> Program:
    """Compile (or reuse a cached build of) `src`. Compile errors raise DojoError with the
    compiler's first lines. `debug` adds sanitizers and the checked STL (C/C++ only)."""
    src = Path(src).expanduser()
    if not src.is_file():
        raise DojoError(f"no such file: {src}")
    src = src.resolve()
    lang = lang_of(src)
    if lang in ("cpp", "c"):
        return _build_native(src, lang, debug=debug, std=std)
    if lang == "java":
        return _build_java(src)
    return _build_python(src)


# ---- C / C++ ---------------------------------------------------------------------------

def _build_native(src: Path, lang: str, *, debug: bool, std: str) -> Program:
    if lang == "cpp":
        compiler = os.environ.get("CXX") or "g++"
        flags = [f"-std={std}", *CXX_FLAGS]
    else:
        compiler = os.environ.get("CC") or "gcc"
        flags = list(C_FLAGS)
    if debug:
        flags += DEBUG_FLAGS
    if not shutil.which(compiler):
        raise DojoError(f"{compiler} not found — install GCC (pacman -S gcc) or set CXX/CC")
    libs = ["-lm"] if lang == "c" else []
    key = _key(_read(src), _local_headers(src), flags + libs, _version(compiler))
    out_dir = _build_root() / key
    exe = out_dir / "prog"
    env = dict(DEBUG_ENV) if debug else {}
    if exe.is_file():
        _touch(out_dir)
        return Program(src, lang, exe=exe, env=env, warnings=_read_text(out_dir / "warnings.txt"),
                       debug=debug, cached=True)
    paths.ensure(out_dir)
    tmp = out_dir / f"prog.{os.getpid()}.tmp"
    res = _compile([compiler, *flags, "-o", str(tmp), str(src), *libs], src)
    if res.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise DojoError(_compile_error(src, res.stderr or res.stdout))
    warnings = _shorten(src, res.stderr).strip()
    (out_dir / "warnings.txt").write_text(warnings)
    os.replace(tmp, exe)
    _prune()
    return Program(src, lang, exe=exe, env=env, warnings=warnings, debug=debug)


_INCLUDE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.M)


def _local_headers(src: Path) -> bytes:
    """Contents of `#include "x.h"` files next to the source, so editing a header rebuilds."""
    out = []
    for name in _INCLUDE.findall(_read(src).decode("utf-8", "replace")):
        p = src.parent / name
        if p.is_file():
            out.append(name.encode() + b"\0" + _read(p))
    return b"\0".join(out)


# ---- Java ------------------------------------------------------------------------------

def _java() -> str:
    return shutil.which("java") or "java"


def _build_java(src: Path) -> Program:
    if not shutil.which("javac"):
        raise DojoError("javac not found — install a JDK (pacman -S jdk21-openjdk)")
    source = _read(src)
    key = _key(source, b"", ["javac", "-encoding", "UTF-8"], _version("javac", "-version"))
    out_dir = _build_root() / key
    classes = out_dir / "classes"
    main = find_main_class(source.decode("utf-8", "replace"))
    if (out_dir / "ok").is_file():
        _touch(out_dir)
        return Program(src, "java", classpath=classes, main_class=_pick_main(main, classes, src),
                       warnings=_read_text(out_dir / "warnings.txt"), cached=True)
    paths.ensure(out_dir)
    staging = Path(tempfile.mkdtemp(prefix="classes.", dir=out_dir))
    res = _compile(["javac", "-encoding", "UTF-8", "-d", str(staging), str(src)], src)
    if res.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise DojoError(_compile_error(src, res.stderr or res.stdout))
    shutil.rmtree(classes, ignore_errors=True)
    os.replace(staging, classes)
    warnings = _shorten(src, res.stderr).strip()
    (out_dir / "warnings.txt").write_text(warnings)
    (out_dir / "ok").write_text("")
    _prune()
    return Program(src, "java", classpath=classes, main_class=_pick_main(main, classes, src),
                   warnings=warnings)


def _pick_main(found: str | None, classes: Path, src: Path) -> str:
    if found and (classes / f"{found}.class").is_file():
        return found
    for guess in ("Main", src.stem):
        if (classes / f"{guess}.class").is_file():
            return guess
    raise DojoError(f"no class with `static void main(String[] args)` in {src.name}")


_JAVA_NOISE = re.compile(r'//[^\n]*|/\*.*?\*/|"""(?:\\.|[^\\])*?"""|"(?:\\.|[^"\\\n])*"|'
                         r"'(?:\\.|[^'\\\n])*'", re.S)
_TYPE_DECL = re.compile(r"\b(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
_MAIN = re.compile(r"\bstatic\b[^;{}=]*?\bvoid\s+main\s*\(")
_INNER = re.compile(r"\{[^{}]*\}")


def find_main_class(source: str) -> str | None:
    """Name of the top-level class that declares `static void main`, preferring a public one.
    Works for a non-public `class Main` in a file with any name."""
    text = _JAVA_NOISE.sub(lambda m: " " if m.group(0).startswith("/") else '""', source)
    with_main: list[tuple[str, bool]] = []
    depth = 0
    for m in re.finditer(r"[{}]|" + _TYPE_DECL.pattern, text):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            body = _body_after(text, m.end())
            prev = max(text.rfind(";", 0, m.start()), text.rfind("}", 0, m.start()))
            public = re.search(r"\bpublic\b", text[prev + 1:m.start()]) is not None
            if body is not None and _MAIN.search(body):
                with_main.append((m.group(1), public))
    for name, public in with_main:
        if public:
            return name
    return with_main[0][0] if with_main else None


def _body_after(text: str, pos: int) -> str | None:
    """The members of the class whose `{` follows `pos`, with nested bodies emptied."""
    start = text.find("{", pos)
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body = text[start + 1:i]
                break
    else:
        body = text[start + 1:]
    while True:
        flat = _INNER.sub("{}", body)
        if flat == body:
            return flat
        body = flat


# ---- Python ----------------------------------------------------------------------------

def _build_python(src: Path) -> Program:
    text = _read(src)
    try:
        compile(text, str(src), "exec")
    except SyntaxError as e:
        where = f"line {e.lineno}" if e.lineno else "?"
        line = (e.text or "").rstrip()
        raise DojoError(f"syntax error in {src.name}, {where}: {e.msg}" + (f"\n    {line}" if line else "")) from None
    # The generator helpers (`from dojo.gen import *`) must import even when dojo isn't installed.
    root = str(Path(__file__).resolve().parents[2])
    pp = os.environ.get("PYTHONPATH")
    return Program(src, "py", env={"PYTHONPATH": root + (os.pathsep + pp if pp else "")}, cached=True)


# ---- helpers ---------------------------------------------------------------------------

def _build_root() -> Path:
    return paths.cache_dir() / "build"


def _key(source: bytes, extra: bytes, flags: list[str], version: str) -> str:
    h = hashlib.sha256()
    for part in (source, extra, "\0".join(flags).encode(), version.encode()):
        h.update(len(part).to_bytes(8, "little"))
        h.update(part)
    return h.hexdigest()[:24]


@functools.cache
def _version(tool: str, flag: str = "--version") -> str:
    try:
        res = subprocess.run([tool, flag], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return tool
    lines = (res.stdout + res.stderr).strip().splitlines()
    return f"{shutil.which(tool)} {lines[0] if lines else ''}"


def _compile(argv: list[str], src: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              cwd=src.parent, timeout=COMPILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise DojoError(f"compiling {src.name} took over {COMPILE_TIMEOUT} s — gave up") from None
    except OSError as e:
        raise DojoError(f"couldn't run {argv[0]}: {e.strerror}") from None


def _compile_error(src: Path, text: str) -> str:
    lines = _shorten(src, text).rstrip().splitlines()
    shown = lines[:ERROR_LINES]
    more = f"\n… {len(lines) - len(shown)} more lines" if len(lines) > len(shown) else ""
    return f"compile error in {src.name}:\n" + "\n".join(shown) + more


def _shorten(src: Path, text: str) -> str:
    """Compiler messages name files by absolute path; the file name is enough."""
    return text.replace(str(src.parent) + os.sep, "")


def _read(p: Path) -> bytes:
    try:
        return p.read_bytes()
    except OSError as e:
        raise DojoError(f"can't read {p}: {e.strerror}") from None


def _read_text(p: Path) -> str:
    try:
        return p.read_text()
    except OSError:
        return ""


def _touch(d: Path) -> None:
    try:
        os.utime(d)
    except OSError:
        pass


def _prune() -> None:
    """Keep the build cache bounded: drop the least recently used builds beyond KEEP_BUILDS."""
    root = _build_root()
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return
    if len(dirs) <= KEEP_BUILDS:
        return
    dirs.sort(key=lambda d: d.stat().st_mtime)
    for d in dirs[:len(dirs) - KEEP_BUILDS]:
        shutil.rmtree(d, ignore_errors=True)
