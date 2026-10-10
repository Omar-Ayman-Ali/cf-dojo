"""Analytics: overview numbers, insights, tag focus math, `dojo status` and `dojo weak`."""
from __future__ import annotations

import datetime as dt
import json
import unittest

from dojo.cf import analysis
from dojo.errors import DojoError
from dojo.commands.weak import parse_band
from tests.fixtures import (capture_term, contest, make_snapshot, prob, rating_change, run_cli, sub,
                            ts)


def texts(snap) -> list[str]:
    return [i.text for i in analysis.overview(snap).insights]


def rich_snapshot(**kw):
    """747-rated, a few solves this week, one group solve, one unsolved problem from a rated round."""
    problems = [prob("2227A", 800, ["implementation"]), prob("2227B", 800, ["greedy"]),
                prob("2227C", 900, ["math"]), prob("1900C", 1200, ["math"])]
    subs = [
        sub("2227A", "WRONG_ANSWER", ts(10, hour=10), ptype="CONTESTANT"),
        sub("2227A", "OK", ts(10, hour=11), ptype="CONTESTANT"),
        sub("2227B", "OK", ts(1)),
        sub("219158A", "OK", ts(2)),
        sub("1900C", "WRONG_ANSWER", ts(0, hour=8)),
        sub("1900C", "WRONG_ANSWER", ts(0, hour=9)),
        sub("1900C", "OK", ts(0, hour=10)),
    ]
    rounds = [rating_change(2227, "Codeforces Round 1096 (Div. 3)", 0, 747, ts(10, hour=13))]
    contests = [contest(2227, "Codeforces Round 1096 (Div. 3)", ts(10, hour=9))]
    args = dict(problems=problems, submissions=subs, rating_history=rounds, contests=contests)
    args.update(kw)
    return make_snapshot(**args)


class OverviewTest(unittest.TestCase):
    def test_numbers(self):
        ov = analysis.overview(rich_snapshot())
        self.assertEqual((ov.rating, ov.rank, ov.to_target, ov.contests), (747, "newbie", 453, 1))
        self.assertEqual((ov.solved_total, ov.solved_problemset, ov.solved_groups), (4, 3, 1))
        self.assertEqual(ov.verdicts["OK"], 4)
        self.assertEqual(ov.verdicts["WRONG_ANSWER"], 3)
        self.assertAlmostEqual(ov.wa_per_ac, 0.75)
        self.assertAlmostEqual(ov.first_try_rate, 0.5)        # 2227B and 219158A, of 4
        self.assertEqual(ov.week_start, dt.date(2026, 10, 3))   # weeks start on Saturday
        self.assertEqual(ov.week_solved, 3)                     # Sun, Mon, Tue
        self.assertEqual((ov.streak, ov.best_streak, ov.active_today), (3, 3, True))
        self.assertEqual(ov.by_rating, {800: 2, 1200: 1})
        self.assertEqual(len(ov.daily), 28)
        self.assertEqual(len(ov.weekly), 12)
        self.assertEqual(ov.daily[-1], (dt.date(2026, 10, 6), 1))
        self.assertEqual(ov.last_ac.date(), dt.date(2026, 10, 6))
        prios = [i.priority for i in ov.insights]
        self.assertEqual(prios, sorted(prios, reverse=True))

    def test_no_submissions_unrated(self):
        snap = make_snapshot()
        ov = analysis.overview(snap)
        self.assertIsNone(ov.rating)
        self.assertIsNone(ov.to_target)
        self.assertEqual(ov.rank, "unrated")
        self.assertEqual((ov.solved_total, ov.wa_per_ac, ov.first_try_rate, ov.comfort), (0, 0.0, 0.0, 800))
        self.assertIsNone(ov.last_ac)
        self.assertIn("No submissions yet", ov.insights[0].text)
        term, _ = capture_term()
        full = analysis.render_status(ov, term)
        self.assertIn("unrated · target 1200 (Pupil)", full)
        self.assertIn("none yet", full)
        compact = analysis.render_status(ov, term, compact=True)
        self.assertLessEqual(len(compact.splitlines()), 3)

    def test_rendering_survives_small_terminals(self):
        ov = analysis.overview(rich_snapshot())
        for width in (40, 60, 120):
            term, _ = capture_term(width)
            self.assertIn("453 to Pupil", analysis.render_status(ov, term))
            self.assertLessEqual(len(analysis.render_status(ov, term, compact=True).splitlines()), 3)

    def test_target_reached(self):
        snap = rich_snapshot(rating_history=[rating_change(2227, "R", 0, 1250, ts(10))])
        ov = analysis.overview(snap)
        self.assertEqual(ov.to_target, -50)
        term, _ = capture_term()
        self.assertIn("target reached", analysis.render_status(ov, term))
        self.assertFalse(any("rating to" in t for t in texts(snap)))


class InsightTest(unittest.TestCase):
    def test_volume_drop(self):
        subs = [sub(f"{2000 + i}A", "OK", ts(25 + i)) for i in range(8)]
        subs += [sub("2100A", "OK", ts(5)), sub("2101A", "OK", ts(1))]
        found = [t for t in texts(make_snapshot(submissions=subs)) if "down from" in t]
        self.assertEqual(len(found), 1)
        self.assertIn("2 solves in the last 3 weeks, down from 8", found[0])

    def test_inactivity_merges_with_volume_drop(self):
        subs = [sub(f"{2000 + i}A", "OK", ts(25 + i)) for i in range(8)] + [sub("2100A", "OK", ts(10))]
        t = texts(make_snapshot(submissions=subs))
        self.assertTrue(any(x.startswith("No AC since Sat 26 Sep (10 days); 1 solves") for x in t), t)

    def test_inactivity_alone(self):
        t = texts(make_snapshot(submissions=[sub("2000A", "OK", ts(10))]))
        self.assertTrue(any("No accepted problem since Sat 26 Sep (10 days)" in x for x in t), t)

    def test_streak_alive(self):
        subs = [sub("2000A", "OK", ts(1)), sub("2001A", "OK", ts(2))]
        self.assertIn("2-day streak — solve one today to keep it.", texts(make_snapshot(submissions=subs)))
        subs.append(sub("2002A", "OK", ts(0)))                 # solved today: nothing to warn about
        self.assertFalse(any("streak" in x for x in texts(make_snapshot(submissions=subs))))

    def test_debugging(self):
        subs = [sub(f"{2000 + i}A", "OK", ts(1)) for i in range(10)]
        subs += [sub("2000A", "WRONG_ANSWER", ts(2)) for _ in range(12)]
        t = [x for x in texts(make_snapshot(submissions=subs)) if "wrong answers" in x]
        self.assertEqual(len(t), 1)
        self.assertIn("12 wrong answers vs 10 accepted (1.20 per AC)", t[0])
        self.assertIn("1 of your 10 solves needed 3+ failed attempts", t[0])
        self.assertIn("dojo stress", t[0])

    def test_old_compiler(self):
        subs = [sub("2000A", "OK", ts(1), lang="C++17 (GCC 7-32)"), sub("2001A", "OK", ts(0))]
        t = [x for x in texts(make_snapshot(submissions=subs)) if "compiler" in x]
        self.assertEqual(len(t), 1)
        self.assertIn("1 of your last 2 submissions used C++17 (GCC 7-32), a 32-bit compiler", t[0])
        self.assertIn(analysis.SAFE_COMPILER, t[0])
        self.assertFalse(any("compiler" in x for x in texts(make_snapshot(submissions=[sub("2000A")]))))

    def test_compiler_issue(self):
        cases = {"C++17 (GCC 7-32)": "a 32-bit compiler", "C++23 (GCC 14-64, msys2)": None,
                 "GNU G++17 7.3.0": "a 32-bit compiler", "GNU G++17 9.2.0 (64 bit, msys 2)": "an old compiler (GCC 9)",
                 "GNU G++20 13.2 (64 bit, winlibs)": None, "Java 21 64bit": None, "Python 3": None,
                 "Clang++20 Diagnostics": None}
        for lang, want in cases.items():
            self.assertEqual(analysis.compiler_issue(lang), want, lang)

    def test_unauthenticated(self):
        t = texts(rich_snapshot(authenticated=False))
        self.assertTrue(any("CF_API_KEY/CF_API_SECRET" in x and "1 group solve " in x for x in t), t)
        self.assertFalse(any("CF_API_KEY" in x for x in texts(rich_snapshot())))

    def test_target_and_upsolve(self):
        t = texts(rich_snapshot())
        self.assertTrue(any(x.startswith("453 rating to Pupil. You solved 1 problem in your rated round") for x in t), t)
        up = [x for x in t if "dojo upsolve" in x]
        self.assertEqual(len(up), 1)
        self.assertTrue(up[0].startswith("2227C (900) from Codeforces Round 1096 (Div. 3) is still unsolved"), up)

    def test_no_upsolve_insight_without_problemset(self):
        snap = rich_snapshot()
        snap.loaded.discard("problemset")
        self.assertFalse(any("dojo upsolve" in x for x in texts(snap)))


# A small problemset where the tag numbers can be worked out by hand (default band 800–1200).
POOL = [
    prob("2000A", 800, ["greedy", "math"]), prob("2000B", 900, ["greedy"]), prob("2000C", 1000, ["greedy"]),
    prob("2000D", 1100, ["math"]), prob("2001A", 800, ["implementation"]),
    prob("2001B", 900, ["greedy", "implementation"]), prob("2001C", 1000, ["dp"]),
    prob("2001D", 1200, ["greedy", "*special"]),       # *special: not in the pool
    prob("2002A", 2000, ["greedy"]),                   # outside the band
    prob("1400A", 800, ["greedy"]),                    # older than min_contest_id
]
TAG_SUBS = [
    sub("2000A", "OK", ts(3)),
    sub("2001A", "WRONG_ANSWER", ts(3)), sub("2001A", "OK", ts(2)),
    sub("2000D", "WRONG_ANSWER", ts(2)), sub("2000D", "TIME_LIMIT_EXCEEDED", ts(1)),
    sub("2000D", "COMPILATION_ERROR", ts(1)),          # not judged: doesn't count as an attempt
]


class TagTest(unittest.TestCase):
    def setUp(self):
        self.snap = make_snapshot(problems=POOL, submissions=TAG_SUBS)
        self.stats = {s.tag: s for s in analysis.tag_profile(self.snap)}

    def test_band_and_pool(self):
        rep = analysis.tag_report(self.snap)
        self.assertEqual((rep.low, rep.high, rep.pool, rep.tagged_solved), (800, 1200, 7, 2))
        self.assertNotIn("*special", self.stats)
        self.assertAlmostEqual(rep.fail_prior, 3 / 5)            # 3 failed of 5 judged

    def test_importance_coverage_fail(self):
        g, m, i, d = (self.stats[t] for t in ("greedy", "math", "implementation", "dp"))
        self.assertAlmostEqual(g.importance, 4 / 7)
        self.assertAlmostEqual(m.importance, 2 / 7)
        self.assertEqual((g.solved, m.solved, i.solved, d.solved), (1, 1, 1, 0))
        self.assertAlmostEqual(g.expected, 4 / 7 * 2)
        self.assertEqual((m.failed_attempts, m.attempts), (2, 3))
        self.assertEqual((i.failed_attempts, i.attempts), (1, 2))
        self.assertEqual((d.failed_attempts, d.attempts), (0, 0))
        self.assertAlmostEqual(m.avg_rating, 800)

    def test_focus_formula(self):
        p = 3 / 5
        for s in self.stats.values():
            coverage = (s.solved + 1) / (s.expected + 1)
            fail = (s.failed_attempts + 4 * p) / (s.attempts + 4)
            self.assertAlmostEqual(s.focus, s.importance * (0.5 + fail) / coverage, msg=s.tag)
        order = [s.focus for s in analysis.tag_profile(self.snap)]
        self.assertEqual(order, sorted(order, reverse=True))

    def test_focus_rewards_failures_and_low_coverage(self):
        # Same importance (2/7): math was failed on, implementation less so.
        self.assertGreater(self.stats["math"].focus, self.stats["implementation"].focus)
        # More failures on math raise its focus.
        more = make_snapshot(problems=POOL, submissions=TAG_SUBS + [sub("2000D", "WRONG_ANSWER", ts(0))])
        after = {s.tag: s for s in analysis.tag_profile(more)}
        self.assertGreater(after["math"].focus, self.stats["math"].focus)

    def test_explicit_band(self):
        rep = analysis.tag_report(self.snap, low=900, high=1000)
        self.assertEqual(rep.pool, 4)
        self.assertEqual(rep.tagged_solved, 0)
        with self.assertRaises(DojoError):
            analysis.tag_report(self.snap, low=1300, high=900)

    def test_focus_tags_threshold(self):
        S = analysis.TagStat
        stats = [S("rare", 0.01, 0, 0, 0, 0, None, 9.0), S("a", 0.5, 0, 0, 0, 0, None, 5.0),
                 S("b", 0.05, 0, 0, 0, 0, None, 4.0), S("c", 0.2, 0, 0, 0, 0, None, 3.0),
                 S("d", 0.2, 0, 0, 0, 0, None, 2.0)]
        self.assertEqual(analysis.top_focus(stats), ["a", "b", "c"])
        self.assertEqual(analysis.top_focus(stats, k=1), ["a"])
        self.assertEqual(analysis.focus_tags(self.snap, k=2), [s.tag for s in analysis.tag_profile(self.snap)
                                                             if s.importance >= 0.05][:2])

    def test_empty_problemset(self):
        snap = make_snapshot(submissions=TAG_SUBS + [sub("1900A", "OK", ts(1), rating=800, tags=["math"])])
        rep = analysis.tag_report(snap)
        self.assertEqual(rep.pool, 0)
        self.assertTrue(all(s.importance == 0 and s.focus == 0 for s in rep.tags))
        self.assertEqual(analysis.focus_tags(snap), [])

    def test_group_problems_untagged_unless_archive_knows(self):
        subs = [sub("219158A", "OK", ts(1)), sub("219158B", "OK", ts(1))]
        archive = [{"contestId": 219158, "index": "B", "tags": ["math"], "rating": 900}]
        rep = analysis.tag_report(make_snapshot(problems=POOL, submissions=subs, archive=archive))
        self.assertEqual((rep.untagged_solved, rep.untagged_groups, rep.group_tagged), (1, 1, 1))
        self.assertEqual(rep.tagged_solved, 1)


class StatusCommandTest(unittest.TestCase):
    def test_status_text_and_json(self):
        code, out, err = run_cli(["status"], snap=rich_snapshot())
        self.assertEqual(code, 0, err)
        self.assertIn("453 to Pupil", out)
        self.assertIn("4 · 3 from the problemset · 1 from groups", out)
        self.assertIn("0.75 WA per AC", out)
        code, out, _ = run_cli(["status", "--json"], snap=rich_snapshot())
        doc = json.loads(out)
        self.assertEqual((doc["rating"], doc["to_target"], doc["target_name"]), (747, 453, "Pupil"))
        self.assertEqual(doc["verdicts"], {"OK": 4, "WRONG_ANSWER": 3})
        self.assertEqual(doc["rating_history"][0]["delta"], 747)
        self.assertEqual(len(doc["daily"]), 28)
        self.assertTrue(doc["insights"])

    def test_status_needs_submissions(self):
        snap = make_snapshot()
        snap.loaded.discard("status")
        code, _, err = run_cli(["status"], snap=snap)
        self.assertEqual(code, 1)
        self.assertIn("dojo sync", err)


class WeakCommandTest(unittest.TestCase):
    def test_table_and_notes(self):
        subs = TAG_SUBS + [sub("219158A", "OK", ts(1))]
        code, out, err = run_cli(["weak", "--all"], snap=make_snapshot(problems=POOL, submissions=subs))
        self.assertEqual(code, 0, err)
        self.assertIn("FOCUS NEXT", out)
        for tag in ("greedy", "math", "implementation", "dp"):
            self.assertIn(tag, out)
        self.assertIn("1 of your 3 solved problems have no tags (all group problems)", out)

    def test_json_and_band(self):
        code, out, _ = run_cli(["weak", "--json", "--band", "900-1000"],
                               snap=make_snapshot(problems=POOL, submissions=TAG_SUBS))
        doc = json.loads(out)
        self.assertEqual((doc["band"], doc["pool"]), ([900, 1000], 4))
        self.assertEqual(code, 0)

    def test_bad_band_and_empty_problemset(self):
        snap = make_snapshot(problems=POOL, submissions=TAG_SUBS)
        for band in ("abc", "1000-900"):
            code, _, err = run_cli(["weak", "--band", band], snap=snap)
            self.assertEqual(code, 1, band)
            self.assertIn("--band", err)
        code, _, err = run_cli(["weak"], snap=make_snapshot(submissions=TAG_SUBS))
        self.assertEqual(code, 1)
        self.assertIn("no problemset problems", err)

    def test_parse_band(self):
        self.assertEqual(parse_band("900-1400"), (900, 1400))
        self.assertEqual(parse_band(" 900 – 1400 "), (900, 1400))
        self.assertEqual(parse_band("900..1400"), (900, 1400))


if __name__ == "__main__":
    unittest.main()
