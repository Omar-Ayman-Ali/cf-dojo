"""dojo web: the JSON views, drill sessions, and the server's routing and access checks."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from dojo.config import Config
from dojo.errors import DojoError
from dojo.web import api
from dojo.web.server import App, _source, serve
from tests.fixtures import TempHome, contest, make_snapshot, rating_change, sub, temp_state, ts
from tests.test_planning import pool


def snap_with_history():
    probs = pool()
    subs = [sub("2000A", "WRONG_ANSWER", ts(30)), sub("2000A", "WRONG_ANSWER", ts(30)),
            sub("2000A", "WRONG_ANSWER", ts(30)), sub("2000A", "OK", ts(29)),
            sub("2001B", "WRONG_ANSWER", ts(3)), sub("2002A", "OK", ts(1))]
    return make_snapshot(
        problems=probs, submissions=subs,
        rating_history=[rating_change(2000, "Codeforces Round 2000 (Div. 3)", 0, 640, ts(60))],
        contests=[contest(2100, "Codeforces Round 2100 (Div. 3)", ts(-2), phase="BEFORE")])


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.snap = snap_with_history()
        self.state = temp_state()

    def test_status_has_heatmap_and_json_safe(self):
        d = api.status(self.snap)
        self.assertEqual(len(d["heatmap"]), api.HEATMAP_DAYS)
        self.assertEqual(d["heatmap"][-1]["date"], self.snap.today.isoformat())
        json.dumps(d, default=str)

    def test_today_then_skip(self):
        plan = api.today(self.snap, self.state)
        self.assertTrue(plan["items"])
        first = plan["items"][0]
        self.assertTrue({"key", "slot", "label", "name", "url", "done", "note", "tags"} <= set(first))
        again = api.today(self.snap, self.state)
        self.assertEqual([i["key"] for i in again["items"]], [i["key"] for i in plan["items"]])
        after = api.skip(self.snap, self.state, first["key"])
        self.assertEqual(after["skipped"], first["key"])
        self.assertNotIn(first["key"], [i["key"] for i in after["items"]])

    def test_retry_and_upsolve_shapes(self):
        r = api.retry(self.snap, self.state)
        self.assertEqual(set(r), {"due", "unsolved", "later", "stages"})
        self.assertIn("2001B", [x["key"] for x in r["unsolved"]])
        self.assertIn("source", r["unsolved"][0])
        u = api.upsolve(self.snap)
        self.assertEqual(set(u), {"comfort", "items", "hidden"})

    def test_contests(self):
        rows = api.upcoming(self.snap, days=7)
        self.assertEqual([r["id"] for r in rows], [2100])
        self.assertIn("div1_only", rows[0])
        self.assertIn("BEGIN:VCALENDAR", api.ics(self.snap, days=7))

    def test_java_sheet(self):
        secs = api.java_sheet()
        self.assertTrue(secs)
        kinds = {b["type"] for s in secs for b in s["blocks"]}
        self.assertEqual(kinds, {"text", "code", "table"})
        code = next(b for s in secs for b in s["blocks"] if b["type"] == "code")
        self.assertFalse(code["code"].startswith((" ", "\n")))

    def test_weak_band(self):
        doc = api.weak(self.snap, band="800-1000")
        self.assertEqual(doc["band"], [800, 1000])
        self.assertEqual(len(doc["default_band"]), 2)
        with self.assertRaises(DojoError):
            api.weak(self.snap, band="high")

    def test_recent_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.cpp").write_text("")
            (root / "sub").mkdir()
            (root / "sub" / "B.java").write_text("")
            (root / "notes.txt").write_text("")
            (root / ".cph").mkdir()
            (root / ".cph" / "x.cpp").write_text("")
            (root / ".cph" / ".a.cpp_0.prob").write_text(json.dumps(
                {"srcPath": str(root / "a.cpp"), "tests": [{"input": "1", "output": "1"}, {"input": "2", "output": "2"}]}))
            files = {f["name"]: f for f in api.recent_files(root)}
            self.assertEqual(set(files), {"a.cpp", "B.java"})
            self.assertEqual((files["a.cpp"]["samples"], files["B.java"]["samples"]), (2, 0))
            self.assertEqual(api.recent_files(root / "missing"), [])

    def test_solve(self):
        d = api.solve("kmap", "m(0,2,5,7) d(1)", "A'C' + AC")
        self.assertEqual(d["answer"], "A'C' + AC")
        self.assertTrue(d["verdict"]["ok"])
        with self.assertRaises(DojoError):
            api.solve("nope", "x", None)
        with self.assertRaises(DojoError):
            api.solve("kmap", "  ", None)


class DrillSessionTest(unittest.TestCase):
    def test_hint_retry_verdict_then_expired(self):
        state = temp_state()
        ds = api.DrillSessions()
        q = ds.next(["zscore"], 1, seed=7)
        self.assertEqual(q["topic"], "zscore")
        self.assertEqual(ds.answer(state, q["id"], "?")["kind"], "hint")
        self.assertEqual(ds.answer(state, q["id"], "banana")["kind"], "retry")
        self.assertEqual(state.get("drill", []), [])                 # hints and unreadable answers aren't recorded
        _, _, question, _ = ds._q[q["id"]]
        v = ds.answer(state, q["id"], question.answer)
        self.assertEqual((v["kind"], v["ok"]), ("verdict", True))
        self.assertEqual(len(state.get("drill", [])), 1)
        with self.assertRaises(DojoError):
            ds.answer(state, q["id"], "1")

    def test_reveal_counts_as_wrong(self):
        state = temp_state()
        ds = api.DrillSessions()
        q = ds.next(["base"], 2, seed=1)
        v = ds.answer(state, q["id"], "!")
        self.assertFalse(v["ok"])
        self.assertTrue(v["revealed"])
        self.assertEqual(v["message"], "")
        self.assertFalse(state.get("drill")[0]["ok"])

    def test_unknown_topics_fall_back_to_all_and_store_is_bounded(self):
        ds = api.DrillSessions()
        q = ds.next(["nonsense"], 9, seed=3)
        self.assertLessEqual(q["level"], q["levels"])
        for i in range(ds.LIMIT + 5):
            ds.next(["twos"], 1, seed=i)
        self.assertEqual(len(ds._q), ds.LIMIT)


class SourceCheckTest(unittest.TestCase):
    def test_only_existing_solution_files(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.cpp"
            f.write_text("int main(){}")
            self.assertEqual(_source(str(f)), f.resolve())
            with self.assertRaises(DojoError):
                _source(str(Path(d) / "missing.cpp"))
            (Path(d) / "secret.txt").write_text("x")
            with self.assertRaises(DojoError):
                _source(str(Path(d) / "secret.txt"))


class FixedApp(App):
    def __init__(self, snap, **kw):
        super().__init__(Config(), **kw)
        self._fixed = snap

    def snapshot(self, *, refresh=False):
        return self._fixed


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = TempHome()
        cls.home.__enter__()
        cls.app = FixedApp(snap_with_history(), offline=True)
        cls.httpd = serve(cls.app, 0)
        cls.base = f"http://127.0.0.1:{cls.app.port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.home.__exit__()

    def req(self, path, body=None, token=True, headers=None):
        h = dict(headers or {})
        if token:
            h["X-Dojo-Token"] = self.app.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read(), e.headers

    def test_page_carries_token_and_csp(self):
        code, body, headers = self.req("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(self.app.token.encode(), body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])

    def test_api_needs_token_and_own_host(self):
        self.assertEqual(self.req("/api/today", token=False)[0], 403)
        self.assertEqual(self.req("/api/today", headers={"X-Dojo-Token": "wrong"}, token=False)[0], 403)
        self.assertEqual(self.req("/api/today", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("/", token=False, headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("/api/drill/next", {"topics": ["twos"]}, token=False)[0], 403)
        self.assertEqual(self.req("/api/contests.ics", token=False)[0], 403)

    def test_get_routes(self):
        for path in ("/api/meta", "/api/status", "/api/today", "/api/weak", "/api/upsolve?all=1", "/api/retry",
                     "/api/contests?days=7", "/api/drill/topics", "/api/java"):
            code, body, _ = self.req(path)
            self.assertEqual(code, 200, (path, body[:200]))
            json.loads(body)
        self.assertEqual(self.req("/api/nope")[0], 404)

    def test_static_files_and_no_traversal(self):
        for name in ("app.js", "app.css", "favicon.svg"):
            self.assertEqual(self.req(f"/static/{name}", token=False)[0], 200)
        self.assertEqual(self.req("/static/..%2Fserver.py", token=False)[0], 404)
        self.assertEqual(self.req("/static/../server.py", token=False)[0], 404)

    def test_drill_round_trip_and_errors_are_json(self):
        code, body, _ = self.req("/api/drill/next", {"topics": ["twos"], "level": 1, "seed": 5})
        q = json.loads(body)
        code, body, _ = self.req("/api/drill/answer", {"id": q["id"], "answer": "!"})
        self.assertEqual((code, json.loads(body)["kind"]), (200, "verdict"))
        code, body, _ = self.req("/api/drill/answer", {"id": q["id"], "answer": "1"})
        self.assertEqual(code, 400)
        self.assertIn("expired", json.loads(body)["error"])
        code, body, _ = self.req("/api/today/skip", {})
        self.assertEqual((code, json.loads(body)["error"]), (400, "missing ref"))

    def test_judge_returns_structured_results(self):
        with tempfile.TemporaryDirectory() as d:
            sol = Path(d) / "sol.py"
            sol.write_text("print(int(input()) * 2)\n")
            code, body, _ = self.req("/api/judge", {"action": "test", "file": str(sol), "input": "21"})
            doc = json.loads(body)
            self.assertEqual(code, 200, doc)
            self.assertEqual(doc["command"], "dojo test sol.py -")
            self.assertEqual([(t["verdict"], t["got"]) for t in doc["result"]["tests"]], [("RAN", "42\n")])
            code, body, _ = self.req("/api/judge", {"action": "stress", "file": str(sol), "n": 5})
            self.assertEqual(code, 400)
            self.assertIn("no brute force", json.loads(body)["error"])

    def test_fonts_and_calendar_filters(self):
        code, _, headers = self.req("/static/archivo-latin.woff2", token=False)
        self.assertEqual((code, headers["Content-Type"]), (200, "font/woff2"))
        code, body, _ = self.req(f"/api/contests.ics?t={self.app.token}&id=2100")
        self.assertEqual(code, 200)
        self.assertIn(b"Codeforces Round 2100", body)
        code, body, _ = self.req(f"/api/contests.ics?t={self.app.token}&id=999")
        self.assertNotIn(b"BEGIN:VEVENT", body)

    def test_judge_rejects_non_source(self):
        code, body, _ = self.req("/api/judge", {"action": "test", "file": "/etc/passwd"})
        self.assertEqual(code, 400)
        self.assertIn("isn't a solution file", json.loads(body)["error"])

    def test_sync_refused_offline(self):
        code, body, _ = self.req("/api/sync", {})
        self.assertEqual(code, 400)

    def test_state_lands_in_dojo_home(self):
        self.req("/api/today")
        self.assertTrue(any(Path(os.environ["DOJO_HOME"]).rglob("state.json")))


if __name__ == "__main__":
    unittest.main()
