import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from dojo.cf import contests
from dojo.config import ClassSlot, Config
from tests.fixtures import CAIRO, NOW, capture_term, contest, make_snapshot, run_cli


def at(y, mo, d, h, mi=0, tz=CAIRO) -> int:
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=tz).timestamp())


# NOW is Tue 6 Oct 2026 12:00 Cairo (UTC+3 until 29 Oct).
DIV3 = contest(2275, "Codeforces Round 1125 (Div. 3)", at(2026, 10, 7, 17, 35), 9000, "BEFORE")
DIV1 = contest(2273, "Codeforces Round (Div. 1)", at(2026, 10, 11, 21, 35), 9000, "BEFORE")
DIV2 = contest(2274, "Codeforces Round (Div. 2)", at(2026, 10, 11, 21, 35), 9000, "BEFORE")
EDU_CLASH = contest(2280, "Educational Codeforces Round 190 (Rated for Div. 2)", at(2026, 10, 14, 13, 0), 7200, "BEFORE")
LATE = contest(2281, "Codeforces Round 1130 (Div. 2)", at(2026, 10, 9, 2, 35), 7200, "BEFORE")
FAR = contest(2290, "Codeforces Round (Div. 4)", at(2026, 11, 5, 17, 35), 9000, "BEFORE")
DONE = contest(2200, "Codeforces Round 1100 (Div. 3)", at(2026, 9, 30, 17, 35), 9000, "FINISHED")


def snap_with(*cs, cfg=None, now=NOW):
    return make_snapshot(contests=cs, cfg=cfg, now=now)


class UpcomingTest(unittest.TestCase):
    def test_window_order_and_phases(self):
        snap = snap_with(FAR, DIV2, DIV3, DONE, DIV1)
        items = contests.upcoming(snap, days=14)
        self.assertEqual([u.contest.id for u in items], [2275, 2273, 2274])      # by start, then id
        self.assertEqual([u.contest.id for u in contests.upcoming(snap, days=40)][-1], 2290)
        self.assertEqual(contests.upcoming(snap_with(), days=14), [])

    def test_shape_used_by_home_and_bar(self):
        u = contests.upcoming(snap_with(DIV3), days=14)[0]
        self.assertIs(u.contest, DIV3)
        self.assertEqual(u.start.tzinfo, CAIRO)
        self.assertEqual((u.start.hour, u.start.minute), (17, 35))
        self.assertEqual(u.end - u.start, dt.timedelta(minutes=150))
        self.assertTrue(u.recommended)
        self.assertEqual(u.start.timestamp() - NOW, u.starts_in)

    def test_recommended(self):
        for name, want in [("Codeforces Round (Div. 1)", False), ("Codeforces Round (Div. 2)", True),
                           ("Codeforces Round 1125 (Div. 3)", True), ("Codeforces Round (Div. 4)", True),
                           ("Educational Codeforces Round 190 (Rated for Div. 2)", True),
                           ("Codeforces Round 1126 (Div. 1 + Div. 2)", True),
                           ("Kotlin Heroes: Episode 14", False)]:
            c = contest(1, name, NOW + 3600, 7200, "BEFORE")
            self.assertEqual(contests.upcoming(snap_with(c))[0].recommended, want, name)

    def test_running_and_stale_cache(self):
        live = contest(10, "Codeforces Round (Div. 3)", NOW - 1800, 7200, "CODING")
        stale_started = contest(11, "Codeforces Round (Div. 4)", NOW - 600, 7200, "BEFORE")
        stale_over = contest(12, "Codeforces Round (Div. 2)", NOW - 9000, 7200, "BEFORE")
        testing = contest(13, "Codeforces Round (Div. 2)", NOW - 9000, 7200, "SYSTEM_TEST")
        items = contests.upcoming(snap_with(live, stale_started, stale_over, testing))
        self.assertEqual([u.contest.id for u in items], [10, 11])
        self.assertTrue(all(u.running for u in items))
        self.assertEqual(items[0].ends_in, 5400)

    def test_class_clashes(self):
        u = contests.upcoming(snap_with(EDU_CLASH))[0]          # Wed 13:00-15:00
        self.assertEqual([s.what for s in u.clashes], ["Statistics lab (CIS 208)", "Logic Design lab (CIS 203)"])
        after = contest(3, "Codeforces Round (Div. 3)", at(2026, 10, 7, 16, 0), 7200, "BEFORE")
        self.assertEqual(contests.upcoming(snap_with(after))[0].clashes, [])        # touching isn't overlapping
        self.assertEqual(contests.upcoming(snap_with(DIV3))[0].clashes, [])

    def test_clash_across_midnight(self):
        cfg = Config()
        cfg.schedule = [ClassSlot(0, dt.time(0, 30), dt.time(1, 30), "Mon early"),     # Monday
                        ClassSlot(1, dt.time(23, 0), dt.time(1, 0), "Tue night"),      # crosses into Wed
                        ClassSlot(6, dt.time(10, 0), dt.time(11, 0), "Sun morning")]
        sun_night = contest(4, "Codeforces Round (Div. 2)", at(2026, 10, 11, 23, 35), 7200, "BEFORE")
        u = contests.upcoming(snap_with(sun_night, cfg=cfg))[0]
        self.assertEqual([s.what for s in u.clashes], ["Mon early"])
        wed_early = contest(5, "Codeforces Round (Div. 2)", at(2026, 10, 7, 0, 30), 3600, "BEFORE")
        u = contests.upcoming(snap_with(wed_early, cfg=cfg))[0]
        self.assertEqual([s.what for s in u.clashes], ["Tue night"])
        self.assertTrue(u.late)

    def test_long_rounds_never_clash(self):
        week = contest(6, "Kotlin Heroes: Practice 14", at(2026, 10, 7, 17, 35), 7 * 86400, "BEFORE")
        self.assertEqual(contests.upcoming(snap_with(week))[0].clashes, [])

    def test_late_and_timezone(self):
        u = contests.upcoming(snap_with(LATE))[0]
        self.assertTrue(u.late)
        self.assertFalse(contests.upcoming(snap_with(DIV3))[0].late)
        # Egypt leaves summer time on 29 Oct 2026: 15:35 UTC is 17:35 in Cairo afterwards.
        nov = contest(7, "Codeforces Round (Div. 2)", at(2026, 11, 5, 15, 35, dt.timezone.utc), 7200, "BEFORE")
        self.assertEqual(contests.upcoming(snap_with(nov), days=40)[0].start.strftime("%H:%M"), "17:35")
        cfg = Config()
        cfg.timezone = "Asia/Tokyo"
        u = contests.upcoming(snap_with(DIV3, cfg=cfg))[0]       # 14:35 UTC = 23:35 Tokyo
        self.assertEqual(u.start.strftime("%a %H:%M"), "Wed 23:35")
        cfg2 = Config()
        cfg2.timezone = "Pacific/Auckland"                       # 03:35 Thursday: late
        self.assertTrue(contests.upcoming(snap_with(DIV3, cfg=cfg2))[0].late)


class RenderTest(unittest.TestCase):
    def test_compact_is_next_recommended(self):
        term, _ = capture_term()
        items = contests.upcoming(snap_with(DIV1, DIV3, EDU_CLASH))
        line = contests.render_upcoming(items, term, compact=True)
        self.assertIn("Codeforces Round 1125 (Div. 3)", line)
        self.assertIn("Wed 07 Oct 17:35", line)
        self.assertIn("in 1d 5h", line)
        self.assertEqual(line.count("\n"), 0)
        only_div1 = contests.upcoming(snap_with(DIV1))
        self.assertEqual(contests.render_upcoming(only_div1, term, compact=True), "")
        self.assertEqual(contests.render_upcoming([], term, compact=True), "")
        self.assertEqual(contests.render_upcoming([], term), "")

    def test_compact_shows_clash_and_running(self):
        term, _ = capture_term()
        line = contests.render_upcoming(contests.upcoming(snap_with(EDU_CLASH)), term, compact=True)
        self.assertIn("⚠ Statistics lab, Logic Design lab", line)
        live = contest(10, "Codeforces Round (Div. 3)", NOW - 1800, 7200, "CODING")
        line = contests.render_upcoming(contests.upcoming(snap_with(live)), term, compact=True)
        self.assertIn("running now, 1h 30m left", line)

    def test_table_markers(self):
        term, _ = capture_term(width=120)
        out = contests.render_upcoming(contests.upcoming(snap_with(DIV3, EDU_CLASH, LATE, DIV1)), term)
        lines = out.splitlines()
        self.assertIn("when", lines[0])
        row = {c: next(line for line in lines if c in line) for c in ("1125", "190", "1130", "(Div. 1)")}
        self.assertIn("★", row["1125"])
        self.assertIn("⚠ Statistics lab, Logic Design lab", row["190"])
        self.assertIn("☾ late", row["1130"])
        self.assertNotIn("★", row["(Div. 1)"])
        self.assertIn("1d 5h", row["1125"])
        one = contests.upcoming(snap_with(contest(3, "Codeforces Round (Div. 3)", at(2026, 10, 10, 13, 0), 3600, "BEFORE")))
        self.assertIn("⚠ OOP lab (CIS 201)", contests.render_upcoming(one, term))
        self.assertIn("2h 30m", row["1125"])

    def test_narrow_terminal(self):
        term, _ = capture_term(width=60)
        long = contest(8, "Codeforces Round 1131 (Div. 2, based on a very long sponsor olympiad name)",
                       NOW + 7200, 7200, "BEFORE")
        out = contests.render_upcoming(contests.upcoming(snap_with(long)), term)
        self.assertIn("…", out)

    def test_next_words(self):
        u = contests.upcoming(snap_with(DIV3))[0]
        self.assertEqual(contests.next_words(u),
                         "Codeforces Round 1125 (Div. 3), tomorrow at 17:35 (in 1d 5h, 2h 30m long).")
        u = contests.upcoming(snap_with(EDU_CLASH))[0]
        self.assertIn("on Wed 14 Oct at 13:00", contests.next_words(u))
        self.assertIn("It overlaps Statistics lab (CIS 208) and Logic Design lab (CIS 203).", contests.next_words(u))
        u = contests.upcoming(snap_with(LATE))[0]
        self.assertIn("on Fri at 02:35", contests.next_words(u))
        self.assertIn("starts at 02:35", contests.next_words(u))


class IcsTest(unittest.TestCase):
    def setUp(self):
        self.snap = snap_with(DIV3, EDU_CLASH, contest(9, "Round; with, commas \\ and a long name " + "x" * 80,
                                                          NOW + 7200, 7200, "BEFORE"))
        self.text = contests.to_ics(contests.upcoming(self.snap), self.snap.now)

    def test_structure(self):
        t = self.text
        self.assertTrue(t.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))
        self.assertTrue(t.endswith("END:VCALENDAR\r\n"))
        self.assertNotIn("\n", t.replace("\r\n", ""))
        self.assertEqual(t.count("BEGIN:VEVENT"), 3)
        self.assertEqual(t.count("BEGIN:VALARM"), 3)
        self.assertEqual(t.count("TRIGGER:-PT30M"), 3)
        self.assertIn("UID:codeforces-contest-2275@dojo\r\n", t)
        self.assertIn("DTSTART:20261007T143500Z\r\n", t)              # 17:35 Cairo = 14:35 UTC
        self.assertIn("DTEND:20261007T170500Z\r\n", t)
        self.assertIn("DTSTAMP:20261006T090000Z\r\n", t)

    def test_folding_and_escaping(self):
        for line in self.text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)
        unfolded = self.text.replace("\r\n ", "")
        self.assertIn("SUMMARY:Round\\; with\\, commas \\\\ and a long name " + "x" * 80 + "\r\n", unfolded)
        self.assertIn("Overlaps Statistics lab (CIS 208) (Wed 12:00–14:00)", unfolded)
        self.assertIn("URL:https://codeforces.com/contests/2275\r\n", unfolded)

    def test_fold_never_splits_a_character(self):
        line = "SUMMARY:" + "é" * 100
        parts = contests._fold(line)
        self.assertEqual("".join(p[1:] if i else p for i, p in enumerate(parts)), line)
        for p in parts:
            self.assertLessEqual(len(p.encode("utf-8")), 75)


class ContestsCommandTest(unittest.TestCase):
    def setUp(self):
        self.snap = snap_with(DIV3, DIV1, DIV2, EDU_CLASH, LATE, FAR, DONE)

    def test_default_table(self):
        code, out, err = run_cli(["contests"], snap=self.snap)
        self.assertEqual(code, 0, err)
        self.assertIn("Codeforces Round 1125 (Div. 3)", out)
        self.assertNotIn("(Div. 1)", out)
        self.assertNotIn("1100", out)
        self.assertNotIn("Div. 4", out)                         # 30 days away
        self.assertIn("1 Div. 1 round hidden: --all", out)
        self.assertIn("Next for you: Codeforces Round 1125 (Div. 3), tomorrow at 17:35", out)

    def test_all_and_days(self):
        code, out, _ = run_cli(["contests", "--all", "--days", "40"], snap=self.snap)
        self.assertEqual(code, 0)
        self.assertIn("Codeforces Round (Div. 1)", out)
        self.assertIn("Codeforces Round (Div. 4)", out)
        self.assertNotIn("hidden", out)
        code, _, err = run_cli(["contests", "--days", "0"], snap=self.snap)
        self.assertEqual(code, 1)
        self.assertIn("--days", err)

    def test_json(self):
        code, out, _ = run_cli(["contests", "--json"], snap=self.snap)
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual([r["id"] for r in rows], [2275, 2281, 2274, 2280])
        edu = rows[3]
        self.assertEqual(edu["start"], "2026-10-14T13:00:00+03:00")
        self.assertEqual([c["what"] for c in edu["clashes"]], ["Statistics lab (CIS 208)", "Logic Design lab (CIS 203)"])
        self.assertTrue(rows[1]["late"])
        self.assertTrue(all(r["recommended"] for r in rows))

    def test_ics_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "cf.ics"
            code, out, _ = run_cli(["contests", "--ics", str(path)], snap=self.snap)
            self.assertEqual(code, 0)
            self.assertIn("Wrote 4 rounds", out)
            data = path.read_bytes()
            self.assertIn(b"\r\nBEGIN:VEVENT\r\n", data)
            self.assertEqual(data.count(b"BEGIN:VEVENT"), 4)
            code, out, _ = run_cli(["contests", "--ics", "-"], snap=self.snap)
            self.assertTrue(out.startswith("BEGIN:VCALENDAR"))

    def test_nothing_upcoming(self):
        code, out, _ = run_cli(["contests"], snap=snap_with(DONE, DIV1))
        self.assertEqual(code, 0)
        self.assertIn("No rounds in the next 14 days (1 Div. 1 round hidden: --all).", out)

    def test_none_recommended(self):
        code, out, _ = run_cli(["contests", "--all"], snap=snap_with(DIV1))
        self.assertEqual(code, 0)
        self.assertIn("None of these suit", out)

    def test_no_contest_data(self):
        snap = snap_with(DIV3)
        snap.loaded.discard("contests")
        code, _, err = run_cli(["contests"], snap=snap)
        self.assertEqual(code, 1)
        self.assertIn("dojo sync", err)

    def test_stale_list_hint(self):
        snap = snap_with(DIV3)
        snap.fetched_at["contests"] = NOW - 3 * 86400
        _, out, _ = run_cli(["contests"], snap=snap)
        self.assertIn("contest list is 3d old", out)


if __name__ == "__main__":
    unittest.main()
