import datetime as dt
import hashlib
import json
import unittest
from fractions import Fraction
from pathlib import Path

from dojo import config
from dojo.cf import metrics
from dojo.cf.api import sign
from dojo.cf.model import Contest, problem_url, split_key
from dojo.drill import core
from dojo.errors import DojoError
from dojo.state import State
from dojo.term import Term, next_rank, pad, rank_of, truncate, width_of
from tests.fixtures import NOW, TempHome, make_snapshot, prob, rating_change, sub, temp_state, ts


class ConfigTest(unittest.TestCase):
    def test_defaults_without_file(self):
        with TempHome():
            cfg = config.load()
        self.assertEqual(cfg.handle, "tourist")
        self.assertEqual(cfg.week_start_day, 5)          # Saturday
        self.assertEqual(len(cfg.schedule), 5)

    def test_default_toml_round_trips(self):
        with TempHome() as home:
            p = Path(home) / "c.toml"
            p.write_text(config.DEFAULT_TOML)
            cfg = config.load(p)
        self.assertEqual(cfg.handle, "tourist")
        self.assertEqual(cfg.java_weekdays, {6, 1, 3})
        self.assertEqual(cfg.schedule[0].day_name, "Sat")
        self.assertEqual(cfg.schedule[-1].start, dt.time(14))

    def test_schedule_parsing(self):
        with TempHome() as home:
            p = Path(home) / "c.toml"
            p.write_text('''
            [[schedule]]
            day = "Sat"
            start = "12:00"
            end = "14:00"
            what = "Algorithms Lab"
            ''')
            cfg = config.load(p)
        self.assertEqual(len(cfg.schedule), 1)
        self.assertEqual(cfg.schedule[0].day_name, "Sat")
        self.assertEqual(cfg.schedule[0].start, dt.time(12))
        self.assertEqual(cfg.schedule[0].end, dt.time(14))
        self.assertEqual(cfg.schedule[0].what, "Algorithms Lab")

    def test_bad_values(self):
        with TempHome() as home:
            p = Path(home) / "c.toml"
            for text in ('[training]\nweekly_goal = "ten"\n', '[training]\nnope = 1\n',
                         '[[schedule]]\nday = "Fun"\nstart = "1:00"\nend = "2:00"\n',
                         '[training]\ntimezone = "Mars/Base"\n', '[training]\nweekly_goal = true\n'):
                p.write_text(text)
                with self.assertRaises(DojoError, msg=text):
                    config.load(p)


class TermTest(unittest.TestCase):
    def test_width_and_pad(self):
        t = Term(color=True, links=False)
        styled = t.s("abc", "accent", "bold")
        self.assertEqual(width_of(styled), 3)
        self.assertEqual(width_of("🔥x"), 3)
        self.assertEqual(width_of(pad(styled, 6, "r")), 6)
        self.assertEqual(truncate("abcdefgh", 5), "abcd…")

    def test_ranks(self):
        self.assertEqual(rank_of(747)[0], "newbie")
        self.assertEqual(rank_of(1200)[0], "pupil")
        self.assertEqual(rank_of(None)[0], "newbie")
        self.assertEqual(next_rank(747), (1200, "pupil"))
        self.assertEqual(next_rank(1399), (1400, "specialist"))

    def test_table_plain(self):
        t = Term(color=False, links=False)
        out = t.table([["a", "1"], ["bbb", "22"]], header=["k", "v"], align="lr")
        self.assertEqual(out.splitlines(), ["  k     v", "  a     1", "  bbb  22"])


class StateTest(unittest.TestCase):
    def test_sections_merge_between_processes(self):
        a = temp_state()
        b = State(a.path)
        a.get("plans", {})["x"] = 1
        a.touch("plans")
        b.set("drill", [1, 2])
        a.save()
        b.save()                       # must not drop a's "plans"
        doc = json.loads(a.path.read_text())
        self.assertEqual(doc, {"plans": {"x": 1}, "drill": [1, 2]})

    def test_corrupt_file_is_set_aside(self):
        s = temp_state()
        s.path.write_text("{nope")
        self.assertIsNone(s.get("plans"))
        self.assertTrue(s.path.with_suffix(".corrupt.json").exists())


class ModelTest(unittest.TestCase):
    def test_keys_and_urls(self):
        self.assertEqual(split_key("2227b"), (2227, "B"))
        self.assertEqual(split_key("1520F2"), (1520, "F2"))
        with self.assertRaises(ValueError):
            split_key("A2227")
        self.assertEqual(problem_url(2227, "B"), "https://codeforces.com/contest/2227/problem/B")
        self.assertEqual(problem_url(596491, "D", "vtfsyP8jkN"),
                         "https://codeforces.com/group/vtfsyP8jkN/contest/596491/problem/D")

    def test_division(self):
        mk = lambda n: Contest(1, n, "CF", "BEFORE", 7200, 0).division
        self.assertEqual(mk("Codeforces Round 1096 (Div. 3)"), "Div. 3")
        self.assertEqual(mk("DeepInfra Round 1 (Codeforces Round 1126, Div. 1 + Div. 2)"), "Div. 1 + Div. 2")
        self.assertEqual(mk("Educational Codeforces Round 170 (Rated for Div. 2)"), "Educational")
        self.assertIsNone(mk("Kotlin Heroes: Practice 12"))

    def test_problem_state(self):
        snap = make_snapshot(submissions=[
            sub("2227B", "COMPILATION_ERROR", ts(5)), sub("2227B", "WRONG_ANSWER", ts(5)),
            sub("2227B", "TIME_LIMIT_EXCEEDED", ts(4)), sub("2227B", "OK", ts(3)),
            sub("2227B", "WRONG_ANSWER", ts(1)), sub("1850A", "WRONG_ANSWER", ts(2)),
            sub("1850B", "COMPILATION_ERROR", ts(2)),
        ])
        st = snap.states["2227B"]
        self.assertTrue(st.solved)
        self.assertEqual(st.wrong_before_ac, 2)      # CE doesn't count
        self.assertEqual(st.wrong_total, 3)
        self.assertEqual(snap.solved, {"2227B"})
        self.assertEqual(snap.attempted_unsolved, {"1850A"})   # CE-only isn't an attempt


class MetricsTest(unittest.TestCase):
    def test_comfort_rating(self):
        subs = [sub(f"{2000 + i}A", "OK", ts(10), rating=800) for i in range(6)]
        subs += [sub("2100A", "OK", ts(10), rating=1000), sub("2101A", "OK", ts(10), rating=1100)]
        snap = make_snapshot(submissions=subs)
        self.assertEqual(metrics.comfort_rating(snap), 800)       # p75 of 6×800,1000,1100 = 800
        snap = make_snapshot(submissions=subs, rating_history=[rating_change(1, "r", 0, 1150, ts(20))])
        self.assertEqual(metrics.comfort_rating(snap), 1000)      # rating 1150 - 100, floored

    def test_streaks(self):
        today = dt.date(2026, 10, 6)
        days = [today - dt.timedelta(days=d) for d in (1, 2, 3, 5, 6)]
        self.assertEqual(metrics.current_streak(days, today), 3)          # alive through yesterday
        self.assertEqual(metrics.current_streak(days + [today], today), 4)
        self.assertEqual(metrics.current_streak(days[2:], today), 0)
        self.assertEqual(metrics.best_streak(days), 3)

    def test_week_counts_start_saturday(self):
        # NOW is Tue 6 Oct; the week began Sat 3 Oct.
        snap = make_snapshot(submissions=[sub("1A", "OK", ts(3, hour=1)),     # Sat 3 Oct 01:00 — this week
                                          sub("2A", "OK", ts(4, hour=23)),    # Fri 2 Oct — last week
                                          sub("3A", "OK", ts(0))])
        start, _, _ = metrics.week_window(snap)
        self.assertEqual(start, dt.date(2026, 10, 3))
        self.assertEqual(sorted(metrics.solved_this_week(snap)), ["1A", "3A"])
        self.assertEqual(metrics.weekly_counts(snap, 2)[-2:], [(dt.date(2026, 9, 26), 1), (dt.date(2026, 10, 3), 2)])


class SignTest(unittest.TestCase):
    def test_matches_documented_scheme(self):
        q = sign("contest.hacks", {"contestId": "566"}, "xxx", "yyy", now=1430431542, rand="123456")
        base = "123456/contest.hacks?apiKey=xxx&contestId=566&time=1430431542#yyy"
        self.assertEqual(q["apiSig"], "123456" + hashlib.sha512(base.encode()).hexdigest())


class DrillCoreTest(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(core.parse_number("3/4"), Fraction(3, 4))
        self.assertEqual(core.parse_number(" -0.25 "), Fraction(-1, 4))
        self.assertEqual(core.parse_number("21.43%"), Fraction(2143, 10000))
        for bad in ("", "abc", "1/x", "--1"):
            with self.assertRaises(ValueError):
                core.parse_number(bad)

    def test_check_number(self):
        exact = Fraction(1, 3)
        self.assertTrue(core.check_number("0.33", exact).ok)
        self.assertTrue(core.check_number("0.3333", exact).ok)
        self.assertTrue(core.check_number("1/3", exact).ok)
        self.assertFalse(core.check_number("0.34", exact).ok)
        self.assertTrue(core.check_number("zz", exact).retry)
        self.assertTrue(core.check_number("21.43%", Fraction(2143, 100), pct=True).ok)
        self.assertFalse(core.check_number("2", Fraction(5, 2), decimals=None).ok)

    def test_fmt_number(self):
        self.assertEqual(core.fmt_number(Fraction(5, 2), 0), "3")
        self.assertEqual(core.fmt_number(Fraction(-1, 8), 2), "-0.13")
        self.assertEqual(core.fmt_number(Fraction(1, 1000), 2), "0.00")
        self.assertEqual(core.fmt_number(2.5, 2), "2.50")


if __name__ == "__main__":
    unittest.main()
