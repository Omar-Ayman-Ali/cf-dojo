"""Codeforces API client.

- At most one call per 2 seconds (Codeforces' documented limit), enforced across processes
  with a lock file, so a status-bar `dojo bar` and a terminal `dojo sync` can't trip it.
- Signed calls (apiKey + time + apiSig) when a key is configured: user.status then includes
  private-group submissions.
- Retries "Call limit exceeded" and 5xx with backoff; anything else raises CFError.
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dojo import __version__

BASE = "https://codeforces.com/api/"
MIN_INTERVAL = 2.0
USER_AGENT = f"dojo/{__version__} (personal Codeforces coach)"


class CFError(RuntimeError):
    """The API refused, failed, or couldn't be reached."""


def sign(method: str, params: dict[str, str], key: str, secret: str, now: int | None = None,
         rand: str | None = None) -> dict[str, str]:
    """params + apiKey, time and apiSig, per https://codeforces.com/apiHelp (Authorization)."""
    q = dict(params, apiKey=key, time=str(int(time.time()) if now is None else now))
    rand = rand or f"{random.randrange(10**6):06d}"
    base = "&".join(f"{k}={v}" for k, v in sorted(q.items()))
    q["apiSig"] = rand + hashlib.sha512(f"{rand}/{method}?{base}#{secret}".encode()).hexdigest()
    return q


def http_get(url: str, timeout: float = 40.0) -> tuple[int, bytes]:
    """(status, body). HTTP error statuses are returned, not raised; network failures raise CFError."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, body, enc = resp.status, resp.read(), resp.headers.get("Content-Encoding", "")
    except urllib.error.HTTPError as e:
        status, body, enc = e.code, e.read(), e.headers.get("Content-Encoding", "") if e.headers else ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise CFError(f"can't reach {urllib.parse.urlsplit(url).netloc} ({reason})") from None
    if "gzip" in enc.lower():
        body = gzip.decompress(body)
    return status, body


class CFClient:
    def __init__(self, key: str | None = None, secret: str | None = None, *,
                 lock_dir: Path, timeout: float = 40.0):
        self.key, self.secret = key, secret
        self.timeout = timeout
        self.lock_path = lock_dir / "api.lock"

    @property
    def can_sign(self) -> bool:
        return bool(self.key and self.secret)

    def call(self, method: str, params: dict[str, Any] | None = None, *, signed: bool = False) -> Any:
        clean = {k: str(v).lower() if isinstance(v, bool) else str(v)
                 for k, v in (params or {}).items() if v is not None}
        if signed and not self.can_sign:
            raise CFError("signed call needs CF_API_KEY and CF_API_SECRET")
        last = ""
        for attempt in range(4):
            q = sign(method, clean, self.key, self.secret) if signed else clean
            url = BASE + method + ("?" + urllib.parse.urlencode(q) if q else "")
            with self._throttle():
                status, body = http_get(url, self.timeout)
            try:
                doc = json.loads(body)
            except ValueError:
                doc = None
            if isinstance(doc, dict) and doc.get("status") == "OK":
                return doc["result"]
            last = (doc or {}).get("comment") if isinstance(doc, dict) else None
            last = last or f"HTTP {status}"
            if "limit exceeded" in last.lower() or status in (429, 500, 502, 503, 504):
                time.sleep(2.5 * (attempt + 1))
                continue
            raise CFError(f"{method}: {last}")
        raise CFError(f"{method}: Codeforces kept refusing ({last}); try again in a minute")

    def _throttle(self):
        client = self

        class _Throttle:
            def __enter__(self):
                client.lock_path.parent.mkdir(parents=True, exist_ok=True)
                self.f = open(client.lock_path, "a+")
                fcntl.flock(self.f, fcntl.LOCK_EX)
                self.f.seek(0)
                try:
                    prev = float(self.f.read().strip() or 0)
                except ValueError:
                    prev = 0.0
                wait = prev + MIN_INTERVAL - time.time()
                if wait > 0:
                    time.sleep(min(wait, MIN_INTERVAL))
                return self

            def __exit__(self, *exc):
                self.f.seek(0)
                self.f.truncate()
                self.f.write(f"{time.time():.3f}")
                self.f.flush()
                fcntl.flock(self.f, fcntl.LOCK_UN)
                self.f.close()
                return False

        return _Throttle()
