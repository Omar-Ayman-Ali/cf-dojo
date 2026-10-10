"""dojo report: a self-contained, well-formed, escaped HTML page."""
from __future__ import annotations

import os
import unittest
from html.parser import HTMLParser
from unittest import mock

from dojo.commands import report
from tests.fixtures import (TempHome, contest, make_snapshot, prob, rating_change, run_cli, sub, temp_state,
                            ts)

VOID = {"meta", "link", "br", "img", "hr", "input", "circle", "line", "rect", "path", "polyline"}
EVIL = '<script>alert("x")</script> & co'


class Structure(HTMLParser):
    """Checks that every non-void tag is closed in order; collects tags and attributes."""

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> at {self.getpos()} with open {self.stack[-3:]}")
        else:
            self.stack.pop()


def check(test: unittest.TestCase, page: str) -> Structure:
    p = Structure()
    p.feed(page)
    p.close()
    test.assertEqual(p.errors, [])
    test.assertEqual(p.stack, [])
    test.assertTrue(page.startswith("<!doctype html>"))
    test.assertIn("prefers-color-scheme: dark", page)
    for tag, attrs in p.tags:
        test.assertNotIn(tag, ("script", "link", "img", "iframe"))
        test.assertNotIn("src", attrs)
        if tag == "a":
            test.assertTrue(attrs["href"].startswith("https://codeforces.com/"), attrs)
    return p


def rich_snapshot():
    problems = [prob("2227A", 800, ["implementation"]), prob("2227B", 900, ["greedy"], name=EVIL)]
    problems += [prob(f"{c}{i}", r, ["math"]) for c in range(2000, 2010) for i, r in zip("ABCD", (800, 900, 1000, 1200))]
    subs = [sub("2227A", "WRONG_ANSWER", ts(30), ptype="CONTESTANT"), sub("2227A", "OK", ts(30), ptype="CONTESTANT"),
            sub("219158A", "OK", ts(3)), sub("2000A", "OK", ts(0)), sub("2001A", "TIME_LIMIT_EXCEEDED", ts(1))]
    rounds = [rating_change(2226, "Codeforces Round 1095 (Div. 3)", 0, 400, ts(60)),
              rating_change(2227, "Round <1096> & friends", 400, 747, ts(30))]
    return make_snapshot(problems=problems, submissions=subs, rating_history=rounds,
                         contests=[contest(2227, "Round <1096> & friends", ts(30))])


class ReportTest(unittest.TestCase):
    def test_command_writes_page(self):
        with TempHome() as home:
            code, out, err = run_cli(["report"], snap=rich_snapshot(), home=home)
            self.assertEqual(code, 0, err)
            path = os.path.join(home, "data", "report.html")
            self.assertEqual(out.strip(), path)
            with open(path, encoding="utf-8") as f:
                page = f.read()
        p = check(self, page)
        self.assertEqual(sum(1 for t, _ in p.tags if t == "svg"), 3)        # rating, weekly, heatmap
        for text in ("453 to Pupil", "Tags to practise", "Today&#x27;s plan", "Upsolve", "Focus next"):
            self.assertIn(text, page)

    def test_escaping(self):
        page = report.build_report(rich_snapshot(), temp_state())
        check(self, page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<1096>", page)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; co", page)   # upsolve queue
        self.assertIn("Round &lt;1096&gt; &amp; friends", page)

    def test_empty_data(self):
        snap = make_snapshot()
        page = report.build_report(snap, temp_state())
        check(self, page)
        self.assertIn("No rated rounds yet", page)
        self.assertIn("No submissions yet", page)
        snap.loaded.discard("problemset")
        page = report.build_report(snap, temp_state())
        check(self, page)
        self.assertIn("run <code>dojo sync</code>", page)

    def test_heat_levels(self):
        self.assertEqual([report.heat_level(n) for n in range(7)], [0, 1, 2, 3, 3, 4, 4])

    def test_open(self):
        with mock.patch("dojo.commands.report.shutil.which", return_value="/usr/bin/xdg-open"), \
                mock.patch("dojo.commands.report.subprocess.Popen") as popen, TempHome() as home:
            code, out, err = run_cli(["report", "--open"], snap=rich_snapshot(), home=home)
            self.assertEqual(code, 0, err)
            self.assertEqual(popen.call_args.args[0], ["/usr/bin/xdg-open", out.strip()])


if __name__ == "__main__":
    unittest.main()
