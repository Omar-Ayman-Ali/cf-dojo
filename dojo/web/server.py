"""The local web server behind `dojo web`.

Binds to 127.0.0.1 only. Every /api call needs the token baked into the page this server
serves, and the Host header must be this server's own address: another website open in the
browser can neither read the token nor reach the API through DNS rebinding. That matters
because the API compiles and runs files on this machine.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from dojo.cf.snapshot import ALL, Snapshot, load_snapshot
from dojo.config import Config
from dojo.errors import DojoError
from dojo.run import cph
from dojo.state import State
from dojo.web import api

STATIC = Path(__file__).parent / "static"
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8", ".woff2": "font/woff2"}
SNAPSHOT_MAX_AGE = 60            # seconds a loaded snapshot is reused before re-reading the cache
TEST_TIMEOUT = 180
STRESS_TIMEOUT = 600
MAX_BODY = 1 << 20


class App:
    def __init__(self, cfg: Config, *, offline: bool = False, token: str | None = None):
        self.cfg = cfg
        self.offline = offline
        self.token = token or secrets.token_urlsafe(24)
        self.lock = threading.RLock()          # snapshot and state.json: one request at a time
        self.warnings: list[str] = []
        self.drills = api.DrillSessions()
        self._snap: Snapshot | None = None
        self._loaded_at = 0.0
        self.port = 0

    # ---- data ----------------------------------------------------------------------------

    def snapshot(self, *, refresh: bool = False) -> Snapshot:
        if refresh or self._snap is None or time.monotonic() - self._loaded_at > SNAPSHOT_MAX_AGE:
            self._snap = load_snapshot(self.cfg, need=ALL, offline=self.offline, refresh=refresh,
                                       warn=self.warnings.append, note=lambda _m: None)
            self._loaded_at = time.monotonic()
            del self.warnings[:-20]
        return self._snap

    def with_state(self, fn: Callable[[State], Any]) -> Any:
        """Run fn with a fresh State (other dojo processes may have written since) and save it."""
        state = State()
        try:
            return fn(state)
        finally:
            state.save()

    # ---- routes --------------------------------------------------------------------------

    def get(self, path: str, q: dict[str, str]) -> Any:
        with self.lock:
            if path == "/api/meta":
                snap = self.snapshot()
                return api.meta(snap, offline=self.offline, warnings=self.warnings)
            if path == "/api/status":
                return api.status(self.snapshot())
            if path == "/api/today":
                return self.with_state(lambda st: api.today(self.snapshot(), st))
            if path == "/api/weak":
                return api.weak(self.snapshot(), band=q.get("band"))
            if path == "/api/upsolve":
                return api.upsolve(self.snapshot(), all_=q.get("all") == "1")
            if path == "/api/retry":
                return self.with_state(lambda st: api.retry(self.snapshot(), st))
            if path == "/api/contests":
                return api.upcoming(self.snapshot(), days=_int(q.get("days"), 30, 1, 120))
            if path == "/api/drill/topics":
                return self.with_state(api.drill_topics)
        if path == "/api/java":
            return api.java_sheet()
        if path == "/api/files":
            return {"root": str(self.cfg.workspace_path), "files": api.recent_files(self.cfg.workspace_path),
                    "editor": self.cfg.editor}
        raise NotFound(path)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        if path == "/api/judge":
            return self.judge(body)
        if path == "/api/new":
            return self.new(body)
        if path == "/api/open":
            return self.open_file(body)
        with self.lock:
            if path == "/api/sync":
                if self.offline:
                    raise DojoError("dojo web was started with --offline: nothing to sync")
                self.snapshot(refresh=True)
                return api.meta(self._snap, offline=self.offline, warnings=self.warnings)
            if path == "/api/today/reroll":
                return self.with_state(lambda st: api.today(self.snapshot(), st, reroll=True))
            if path == "/api/today/skip":
                return self.with_state(lambda st: api.skip(self.snapshot(), st, _str(body, "ref")))
            if path == "/api/retry/done":
                return self.with_state(lambda st: api.retry_done(self.snapshot(), st, _str(body, "key")))
            if path == "/api/drill/next":
                keys = [str(k) for k in body.get("topics") or []]
                seed = _int(body.get("seed"), secrets.randbelow(10**6), 0, 10**9)
                return self.drills.next(keys, _int(body.get("level"), 2, 1, 5), seed)
            if path == "/api/drill/answer":
                return self.with_state(lambda st: self.drills.answer(st, _str(body, "id"), str(body.get("answer", ""))))
            if path == "/api/solve":
                return api.solve(_str(body, "topic"), str(body.get("text", "")), body.get("check"))
        raise NotFound(path)

    # ---- running things --------------------------------------------------------------------

    def judge(self, body: dict[str, Any]) -> dict[str, Any]:
        action = _str(body, "action")
        src = _source(_str(body, "file"))
        argv: list[str] = []
        stdin: str | None = None
        timeout = TEST_TIMEOUT
        if action == "test":
            argv = ["test", str(src)]
            custom = body.get("input")
            if isinstance(custom, str) and custom.strip():
                argv.append("-")
                stdin = custom if custom.endswith("\n") else custom + "\n"
            elif not cph.cph_tests(src):
                inputs = sorted(src.parent.glob(f"{src.stem}*.in"))
                if not inputs:
                    raise DojoError(f"no CPH samples for {src.name}: paste an input to run it on that")
                argv += [str(p) for p in inputs]
        elif action == "stress":
            argv = ["stress", str(src), "-n", str(_int(body.get("n"), 300, 1, 100000))]
            timeout = STRESS_TIMEOUT
        elif action == "init":
            argv = ["stress", "--init", str(src)]
        else:
            raise DojoError(f"unknown action {action!r}")
        if body.get("debug") and action in ("test", "stress"):
            argv.append("--debug")
        command = "dojo " + shlex.join([a if a != str(src) else src.name for a in argv])
        if action == "init":
            code, out, secs = _dojo(argv, cwd=src.parent, timeout=timeout)
            return {"code": code, "output": out, "seconds": round(secs, 2), "command": command}
        code, out, secs = _dojo([*argv, "--json"], cwd=src.parent, stdin=stdin, timeout=timeout, merge=False)
        try:
            result = json.loads(out.stdout)
        except ValueError:
            text = (out.stderr or out.stdout).strip()
            raise DojoError(text.removeprefix("dojo: ") or f"dojo {action} stopped (exit {code})") from None
        return {"code": code, "result": result, "seconds": round(secs, 2), "command": command}

    def new(self, body: dict[str, Any]) -> dict[str, Any]:
        argv = ["new", _str(body, "id")]
        if body.get("java"):
            argv.append("--java")
        if self.offline:
            argv.insert(0, "--offline")
        code, out, _ = _dojo(argv, cwd=self.cfg.workspace_path if self.cfg.workspace_path.is_dir() else Path.home(),
                             timeout=60)
        path = next((ln.strip() for ln in out.splitlines()
                     if ln.strip().endswith(api.SOURCE_SUFFIXES) and Path(ln.strip()).is_file()), None)
        return {"code": code, "output": out, "path": path}

    def open_file(self, body: dict[str, Any]) -> dict[str, Any]:
        src = _source(_str(body, "file"))
        argv = shlex.split(self.cfg.editor or "")
        if not argv:
            raise DojoError("no editor set: add editor = \"code\" under [workspace] in config.toml")
        try:
            subprocess.Popen([*argv, str(src)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            raise DojoError(f"can't run your editor {argv[0]!r} ({e.strerror or e})") from None
        return {"opened": str(src)}


class NotFound(Exception):
    pass


def _str(body: dict[str, Any], key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise DojoError(f"missing {key}")
    return v.strip()


def _int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _source(text: str) -> Path:
    p = Path(text).expanduser()
    if p.suffix not in api.SOURCE_SUFFIXES:
        raise DojoError(f"{p.name} isn't a solution file ({', '.join(api.SOURCE_SUFFIXES)})")
    if not p.is_file():
        raise DojoError(f"no such file: {p}")
    return p.resolve()


def _dojo(argv: list[str], *, cwd: Path, stdin: str | None = None, timeout: float,
          merge: bool = True) -> tuple[int, Any, float]:
    """Run a dojo command as a child process: (exit code, output, seconds). The output is stdout and
    stderr combined, or with merge=False the CompletedProcess-like pair (.stdout, .stderr)."""
    root = str(Path(__file__).resolve().parents[2])      # the directory holding the dojo package
    env = dict(os.environ, NO_COLOR="1", COLUMNS="100",
               PYTHONPATH=os.pathsep.join(filter(None, [root, os.environ.get("PYTHONPATH")])))
    start = time.monotonic()
    try:
        p = subprocess.run([sys.executable, "-m", "dojo", "--no-color", *argv], cwd=cwd, env=env,
                           input=stdin if stdin is not None else "", text=True, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge else subprocess.PIPE)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        msg = f"stopped: no result after {timeout:g} s"
        if not merge:
            raise DojoError(msg) from None
        return 124, out + "\n" + msg, time.monotonic() - start
    return p.returncode, (p.stdout if merge else p), time.monotonic() - start


def _json_default(o: Any) -> Any:
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "dojo"

        def log_message(self, fmt: str, *args: Any) -> None:     # quiet: errors are reported below
            pass

        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, doc: Any) -> None:
            self._send(status, json.dumps(doc, default=_json_default, ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def _token_ok(self) -> bool:
            return hmac.compare_digest(self.headers.get("X-Dojo-Token", ""), app.token)

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            url = urlsplit(self.path)
            if url.path in ("/", "/index.html"):
                page = (STATIC / "index.html").read_text().replace("__DOJO_TOKEN__", app.token)
                return self._send(HTTPStatus.OK, page.encode(), STATIC_TYPES[".html"], {
                    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                                               "style-src 'self'; script-src 'self'; frame-ancestors 'none'"})
            if url.path.startswith("/static/"):
                name = url.path[len("/static/"):]
                f = STATIC / name
                if "/" in name or not f.is_file() or f.suffix not in STATIC_TYPES:
                    return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return self._send(HTTPStatus.OK, f.read_bytes(), STATIC_TYPES[f.suffix])
            if url.path == "/api/contests.ics":
                if parse_qs(url.query).get("t", [""])[0] != app.token:
                    return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                return self._call(lambda: self._ics(url.query))
            if not url.path.startswith("/api/"):
                return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            if not self._token_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "bad token: reload the page"})
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            self._call(lambda: self._json(HTTPStatus.OK, app.get(url.path, q)))

        def do_POST(self) -> None:
            if not self._host_ok() or not self._token_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden: reload the page"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "expected a JSON object"})
            path = urlsplit(self.path).path
            self._call(lambda: self._json(HTTPStatus.OK, app.post(path, body)))

        def _ics(self, query: str) -> None:
            q = parse_qs(query)
            with app.lock:
                text = api.ics(app.snapshot(), all_=q.get("all", ["0"])[0] == "1",
                               ids={int(i) for i in q.get("id", []) if i.isdigit()},
                               recommended=q.get("rec", ["0"])[0] == "1")
            self._send(HTTPStatus.OK, text.encode(), "text/calendar; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="codeforces.ics"'})

        def _call(self, fn: Callable[[], None]) -> None:
            try:
                fn()
            except NotFound as e:
                self._json(HTTPStatus.NOT_FOUND, {"error": f"no such endpoint: {e}"})
            except DojoError as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:                      # keep serving; show it in the page and the terminal
                traceback.print_exc()
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{e.__class__.__name__}: {e}"})

    return Handler


def serve(app: App, port: int, *, tries: int = 10) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1:port, or the next free port. Sets app.port."""
    last: OSError | None = None
    for p in range(port, port + tries) if port else [0]:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
        except OSError as e:
            last = e
            continue
        httpd.daemon_threads = True
        app.port = httpd.server_address[1]
        return httpd
    raise DojoError(f"no free port from {port} to {port + tries - 1} ({last}) — try --port")
