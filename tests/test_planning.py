"""Planning: today's plan (determinism, slots, reroll, skip), the upsolve queue and the retry queue."""
from __future__ import annotations

import datetime as dt
import json
import unittest

from dojo.cf import recommend
from dojo.cf.model import Problem
from dojo.cf.recommend import PlanItem, Plan
from dojo.cf.upsolve import index_order, mark_resolved, retry_queue, upsolve_queue
from dojo.errors import DojoError
from tests.fixtures import (NOW, TempHome, capture_term, contest, make_snapshot, prob, rating_change,
                            run_cli, sub, temp_state, ts)

TODAY = dt.date(2026, 10, 6)            # a Tuesday: a Java day by default
TAGS = ["greedy", "math", "implementation", "constructive algorithms", "dp", "strings", "sortings"]
RATINGS = (800, 900, 1000, 1100, 1200, 1300, 1400)


def pool(first: int = 2000, n: int = 30) -> list[Problem]:
    """n contests × 7 problems rated 800…1400, tags rotating through TAGS."""
    out = []
    for c in range(first, first + n):
        for j, (idx, r) in enumerate(zip("ABCDEFG", RATINGS)):
            out.append(prob(f"{c}{idx}", r, [TAGS[(c + j) % len(TAGS)]], solved_count=1000 + 37 * c % 5000))
    return out


def plan_snap(**kw):
    args = dict(problems=pool())
    args.update(kw)
    return make_snapshot(**args)


def build(snap, **kw):
    args = dict(day=TODAY, comfort=900, focus=[], size=3, java_day=False, exclude=set())
    args.update(kw)
    return recommend.build_plan(snap, **args)


def keys(plan) -> list[str]:
    return [i.key for i in plan.items]


class SlotTest(unittest.TestCase):
    def test_plan_slots(self):
        self.assertEqual(recommend.plan_slots(0), [])
        self.assertEqual(recommend.plan_slots(1), ["core"])
        self.assertEqual(recommend.plan_slots(2), ["core", "stretch"])
        self.assertEqual(recommend.plan_slots(3), ["warmup", "core", "stretch"])
        self.assertEqual(recommend.plan_slots(4), ["warmup", "core", "core", "stretch"])
        self.assertEqual(recommend.plan_slots(5), ["warmup", "core", "core", "core", "stretch"])
        self.assertEqual(recommend.plan_slots(6), ["warmup", "core", "core", "core", "stretch", "stretch"])
        self.assertEqual(recommend.plan_slots(7).count("core"), 4)

    def test_slot_ranges(self):
        r = recommend.slot_range
        self.assertEqual(r("warmup", 900, 1200), (800, 900))
        self.assertEqual(r("warmup", 800, 1200), (800, 800))          # never below 800
        self.assertEqual(r("core", 900, 1200), (1000, 1100))
        self.assertEqual(r("stretch", 900, 1200), (1200, 1300))
        self.assertEqual(r("stretch", 1300, 1200), (1500, 1500))      # capped at target + 300
        self.assertEqual(r("java", 900, 1200), (800, 800))
        self.assertEqual(r("java", 1200, 1200), (800, 1100))


class CandidateTest(unittest.TestCase):
    def test_filters(self):
        problems = [
            prob("2100A", 900, name="Good"),
            prob("2100B", None, name="Unrated"),
            Problem(2100, "C", "Question", 900, (), 5000, "QUESTION"),
            prob("1400A", 900, name="Too old"),
            prob("2100D", 900, ["*special"], name="Special"),
            prob("2100E", 900, ["interactive"], name="Interactive"),
            prob("2100F", 900, solved_count=100, name="Obscure"),
            prob("2101A", 900, name="Touched"),
            prob("2101B", 900, name="Excluded"),
            prob("2102A", 900, name="Twin Peaks"),
            prob("2104A", 900, name="twin  peaks"),          # Div. 1/2 twin of a touched problem
            prob("2106A", 900, name="Twin Peaks"),           # same name, too far away to be a twin
            prob("100500A", 900, name="Gym"),
            prob("2107A", 900, solved_count=None, name="Unknown popularity"),
        ]
        snap = make_snapshot(problems=problems, submissions=[
            sub("2101A", "WRONG_ANSWER", ts(3)), sub("2102A", "OK", ts(3), name="Twin Peaks")])
        got = [p.key for p in recommend.candidates(snap, {"2101B"})]
        self.assertEqual(got, ["2100A", "2106A", "2107A"])

    def test_archive_solves_are_touched(self):
        snap = make_snapshot(problems=[prob("2100A", 900), prob("2100B", 900)],
                             archive=[{"contestId": 2100, "index": "A", "name": "x"}])
        self.assertEqual([p.key for p in recommend.candidates(snap)], ["2100B"])


class BuildPlanTest(unittest.TestCase):
    def test_deterministic(self):
        a, b = build(plan_snap()), build(plan_snap())
        self.assertEqual(a.to_json(), b.to_json())
        self.assertEqual([i.slot for i in a.items], ["warmup", "core", "stretch"])
        self.assertEqual(Plan.from_json(json.loads(json.dumps(a.to_json()))).to_json(), a.to_json())

    def test_reroll_and_day_change_the_plan(self):
        base = keys(build(plan_snap()))
        self.assertTrue(any(keys(build(plan_snap(), rerolls=r)) != base for r in (1, 2, 3)))
        self.assertTrue(any(keys(build(plan_snap(), day=TODAY + dt.timedelta(days=d))) != base for d in (1, 2, 3)))

    def test_ranges_and_no_repeats(self):
        snap = plan_snap()
        plan = build(snap, size=7, java_day=True)
        self.assertEqual(len(set(keys(plan))), len(plan.items))
        for it in plan.items:
            lo, hi = recommend.slot_range(it.slot, 900, 1200)
            self.assertTrue(lo <= it.rating <= hi, (it, lo, hi))
            self.assertEqual(snap.problems[it.key].rating, it.rating)

    def test_focus_tag_steers_core(self):
        snap = plan_snap(problems=pool() + [prob("2050C", 1000, ["binary search"])])
        plan = build(snap, focus=["binary search", "math"], size=4)
        cores = [i for i in plan.items if i.slot == "core"]
        self.assertEqual((cores[0].key, cores[0].focus_tag), ("2050C", "binary search"))
        self.assertEqual(cores[1].focus_tag, "math")
        self.assertIn("math", snap.problems[cores[1].key].tags)
        self.assertTrue(all(i.focus_tag is None for i in plan.items if i.slot != "core"))

    def test_widening(self):
        snap = make_snapshot(problems=[prob("2100A", 1300)])
        self.assertEqual(keys(build(snap, size=1)), ["2100A"])              # core 1000–1100, widened by 200
        snap = make_snapshot(problems=[prob("2100A", 1500)])
        self.assertEqual(keys(build(snap, size=1)), [])                      # past 3 widenings: slot dropped

    def test_java_slot(self):
        problems = [prob("2100A", 800, ["implementation"]), prob("2100B", 800, ["dp"]),
                    prob("2100C", 1100, ["math"]), prob("2100D", 900, ["math"])]
        plan = build(make_snapshot(problems=problems), size=1, java_day=True)
        java = [i for i in plan.items if i.slot == "java"]
        self.assertEqual([i.key for i in java], ["2100A"])                  # 800 only, preferred tag
        self.assertNotIn("java", [i.slot for i in build(make_snapshot(problems=problems), size=1).items])

    def test_extras_and_exclude(self):
        snap = plan_snap()
        first = keys(build(snap))
        extras = [PlanItem(first[0], "upsolve", 800)]
        plan = build(snap, extras=extras, exclude={first[1]})
        self.assertEqual(plan.items[-1], extras[0])
        self.assertEqual(keys(plan).count(first[0]), 1)
        self.assertNotIn(first[1], keys(plan))

    def test_empty_problemset(self):
        plan = build(make_snapshot(), java_day=True)
        self.assertEqual(plan.items, [])


class TodaysPlanTest(unittest.TestCase):
    def test_persisted_and_reused(self):
        state = temp_state()
        plan = recommend.todays_plan(plan_snap(), state)
        self.assertEqual(plan.day, TODAY)
        self.assertIn("java", [i.slot for i in plan.items])                 # Tuesday
        self.assertEqual(state.get("plans")[TODAY.isoformat()], plan.to_json())
        # A different snapshot later the same day: same plan.
        again = recommend.todays_plan(plan_snap(problems=pool(3000)), state)
        self.assertEqual(again.to_json(), plan.to_json())
        # A fresh state on the same data builds the same plan too.
        self.assertEqual(keys(recommend.todays_plan(plan_snap(), temp_state())), keys(plan))

    def test_past_and_future_days(self):
        state = temp_state()
        with self.assertRaises(DojoError):
            recommend.todays_plan(plan_snap(), state, day=TODAY - dt.timedelta(days=1))
        with self.assertRaises(DojoError):
            recommend.todays_plan(plan_snap(), state, day=TODAY + dt.timedelta(days=1))
        self.assertFalse(state.get("plans"))
        plan = recommend.todays_plan(plan_snap(), state)
        tomorrow = plan_snap(now=NOW + 86400)
        self.assertEqual(recommend.todays_plan(tomorrow, state, day=TODAY).to_json(), plan.to_json())
        with self.assertRaises(DojoError):
            recommend.todays_plan(tomorrow, state, day=TODAY, reroll=True)

    def test_reroll_keeps_done_items(self):
        state = temp_state()
        plan = recommend.todays_plan(plan_snap(), state)
        solved = plan.items[0].key
        snap = plan_snap(submissions=[sub(solved, "OK", ts(0, hour=11))])
        new = recommend.todays_plan(snap, state, reroll=True)
        self.assertEqual(new.rerolls, 1)
        self.assertEqual(new.items[0].key, solved)
        self.assertTrue(recommend.item_done(snap, new.items[0]))
        old_undone = set(keys(plan)[1:])
        self.assertFalse(old_undone & set(keys(new)), (keys(plan), keys(new)))
        self.assertEqual(state.get("plans")[TODAY.isoformat()]["rerolls"], 1)
        self.assertEqual(recommend.todays_plan(plan_snap(), state, reroll=True).rerolls, 2)

    def test_variety_skips_recent_unsolved(self):
        today = keys(recommend.todays_plan(plan_snap(), temp_state()))
        state = temp_state()
        y = (TODAY - dt.timedelta(days=1)).isoformat()
        old = (TODAY - dt.timedelta(days=100)).isoformat()
        state.set("plans", {y: {"day": y, "items": [{"key": k, "slot": "core"} for k in today]},
                            old: {"day": old, "items": []}})
        fresh = keys(recommend.todays_plan(plan_snap(), state))
        self.assertFalse(set(today) & set(fresh))
        self.assertNotIn(old, state.get("plans"))                           # pruned: older than 60 days
        self.assertIn(y, state.get("plans"))

    def test_extras_upsolve_and_retry(self):
        problems = pool() + [prob("2227A", 800), prob("2227B", 900)]
        snap = plan_snap(problems=problems,
                         rating_history=[rating_change(2227, "Codeforces Round 1096 (Div. 3)", 0, 747, ts(20))],
                         submissions=[sub("2227A", "OK", ts(20), ptype="CONTESTANT"),
                                      sub("219158A", "WRONG_ANSWER", ts(4))])
        plan = recommend.todays_plan(snap, temp_state())
        slots = {i.slot: i.key for i in plan.items}
        self.assertEqual(slots["upsolve"], "2227B")
        self.assertEqual(slots["retry"], "219158A")
        self.assertEqual(len(keys(plan)), len(set(keys(plan))))

    def test_needs_problemset_only_to_build(self):
        state = temp_state()
        snap = plan_snap()
        snap.loaded.discard("problemset")
        with self.assertRaises(DojoError):
            recommend.todays_plan(snap, state)
        plan = recommend.todays_plan(plan_snap(), state)
        self.assertEqual(recommend.todays_plan(snap, state).to_json(), plan.to_json())


class ItemDoneTest(unittest.TestCase):
    def test_retry_needs_a_new_ac(self):
        item = PlanItem("2100A", "retry", 900)
        old = make_snapshot(submissions=[sub("2100A", "WRONG_ANSWER", ts(9)), sub("2100A", "WRONG_ANSWER", ts(9)),
                                         sub("2100A", "OK", ts(8))])
        self.assertFalse(recommend.item_done(old, item))
        self.assertTrue(recommend.item_done(old, PlanItem("2100A", "core", 900)))
        # Just after midnight Cairo time counts for the new day.
        late = make_snapshot(submissions=list(old.submissions) + [sub("2100A", "OK", ts(0, hour=0) + 60)])
        self.assertTrue(recommend.item_done(late, item))
        self.assertFalse(recommend.item_done(late, item, day=TODAY + dt.timedelta(days=1)))


class SkipTest(unittest.TestCase):
    def test_skip_refills_same_slot(self):
        state, snap = temp_state(), plan_snap()
        plan = recommend.todays_plan(snap, state)
        core = next(i for i, it in enumerate(plan.items) if it.slot == "core")
        old = plan.items[core]
        new_plan, skipped, new = recommend.skip_item(snap, state, old.key.lower(), reason="seen it")
        self.assertEqual(skipped.key, old.key)
        self.assertIsNotNone(new)
        self.assertEqual(new.slot, "core")
        self.assertNotIn(new.key, keys(plan))
        self.assertEqual(new_plan.items[core], new)
        self.assertEqual(state.get("plans")["_skipped"],
                         [{"key": old.key, "day": TODAY.isoformat(), "slot": "core", "reason": "seen it"}])
        self.assertEqual(state.get("plans")[TODAY.isoformat()], new_plan.to_json())
        # Skipped problems never come back, even on a reroll.
        for _ in range(3):
            self.assertNotIn(old.key, keys(recommend.todays_plan(snap, state, reroll=True)))

    def test_skip_by_position_and_errors(self):
        state, snap = temp_state(), plan_snap()
        plan = recommend.todays_plan(snap, state)
        _, skipped, _ = recommend.skip_item(snap, state, "1")
        self.assertEqual(skipped.key, plan.items[0].key)
        for ref in ("0", "99", "nonsense", "1234Z"):
            with self.assertRaises(DojoError, msg=ref):
                recommend.skip_item(snap, state, ref)
        done_key = recommend.todays_plan(snap, state).items[1].key
        solved = plan_snap(submissions=[sub(done_key, "OK", ts(0))])
        with self.assertRaises(DojoError):
            recommend.skip_item(solved, state, done_key)

    def test_skip_with_nothing_left_drops_the_item(self):
        state = temp_state()
        snap = make_snapshot(problems=[prob("2100A", 1000), prob("2100B", 1000)])
        plan = recommend.todays_plan(snap, state)
        self.assertEqual(len(plan.items), 2)                                 # both 1000s, by widening
        _, _, new = recommend.skip_item(snap, state, plan.items[0].key)
        self.assertIsNone(new)
        self.assertEqual(len(recommend.todays_plan(snap, state).items), 1)

    def test_empty_plan(self):
        with self.assertRaisesRegex(DojoError, "empty"):
            recommend.skip_item(make_snapshot(), temp_state(), "1")


class UpsolveTest(unittest.TestCase):
    def setUp(self):
        problems = [
            prob("2227A", 800), prob("2227B", 800), prob("2227C2", 1000), prob("2227C1", 900), prob("2227D", 1400),
            prob("2241A", 800), prob("2241B", 1100),
            prob("2250A", None), prob("2250B", None), prob("2250C", None), prob("2250D", None),
            prob("2260A", 800),                          # a contest you never entered
            prob("1999A", 800),                          # virtual participation
        ]
        subs = [
            sub("2227A", "OK", ts(150), ptype="CONTESTANT"),
            sub("2227B", "WRONG_ANSWER", ts(150), ptype="CONTESTANT"),
            sub("2241A", "OK", ts(90), ptype="CONTESTANT"),
            sub("2250A", "OK", ts(10), ptype="CONTESTANT"),     # unrated round you took part in
            sub("1999A", "WRONG_ANSWER", ts(5), ptype="VIRTUAL"),
            sub("100500A", "WRONG_ANSWER", ts(3), ptype="CONTESTANT"),
            sub("2260A", "WRONG_ANSWER", ts(2)),                # practice only
        ]
        rounds = [rating_change(2227, "Round 1096", 0, 356, ts(150)), rating_change(2241, "Round 1107", 356, 614, ts(90))]
        contests = [contest(2227, "Round 1096", ts(150, hour=17)), contest(2241, "Round 1107", ts(90, hour=17)),
                    contest(2250, "Round 1110", ts(10, hour=17))]
        self.snap = make_snapshot(problems=problems, submissions=subs, rating_history=rounds, contests=contests)

    def test_order_and_cap(self):
        q = upsolve_queue(self.snap, comfort=800)            # cap 1300
        self.assertEqual([u.key for u in q], ["1999A", "2250B", "2250C", "2241B", "2227B", "2227C1", "2227C2"])
        b = next(u for u in q if u.key == "2227B")
        self.assertTrue(b.attempted)
        self.assertEqual((b.contest_id, b.contest_name, b.index, b.rating), (2227, "Round 1096", "B", 800))
        self.assertFalse(next(u for u in q if u.key == "2227C1").attempted)
        self.assertTrue(next(u for u in q if u.key == "1999A").attempted)

    def test_uncapped(self):
        q = [u.key for u in upsolve_queue(self.snap, comfort=800, uncapped=True)]
        self.assertIn("2227D", q)
        self.assertIn("2250D", q)
        self.assertNotIn("2260A", q)
        self.assertFalse(any(k.startswith("100500") for k in q))

    def test_empty(self):
        self.assertEqual(upsolve_queue(make_snapshot(), 900), [])
        snap = make_snapshot(rating_history=self.snap.rating_history)       # no problemset
        self.assertEqual(upsolve_queue(snap, 900), [])

    def test_index_order(self):
        self.assertEqual(sorted(["D", "C2", "AA", "A", "C1", "B", "C"], key=index_order),
                         ["A", "B", "C", "C1", "C2", "D", "AA"])


def hard_won(key: str, first_ac_days_ago: float, wrong: int = 2, extra_acs=()):
    subs = [sub(key, "WRONG_ANSWER", ts(first_ac_days_ago + 0.1)) for _ in range(wrong)]
    subs.append(sub(key, "OK", ts(first_ac_days_ago)))
    subs += [sub(key, "OK", ts(d)) for d in extra_acs]
    return subs


class RetryTest(unittest.TestCase):
    def test_unsolved_newest_first(self):
        snap = make_snapshot(submissions=[sub("219158A", "WRONG_ANSWER", ts(30)), sub("2100B", "RUNTIME_ERROR", ts(2)),
                                          sub("2100C", "COMPILATION_ERROR", ts(1)), sub("2100D", "OK", ts(1))])
        q = retry_queue(snap, temp_state())
        self.assertEqual([(r.key, r.kind, r.wrong) for r in q], [("2100B", "unsolved", 1), ("219158A", "unsolved", 1)])
        self.assertTrue(all(r.is_due(TODAY) for r in q))

    def test_schedule(self):
        subs = (hard_won("2100A", 5) + hard_won("2100B", 1, wrong=3) + hard_won("2100C", 5, wrong=1)
                + hard_won("2100D", 200) + [sub("2100E", "WRONG_ANSWER", ts(1))])
        state = temp_state()
        q = retry_queue(make_snapshot(submissions=subs), state, today=TODAY)
        self.assertEqual([(r.key, r.kind) for r in q],
                         [("2100A", "resolve"), ("2100E", "unsolved"), ("2100B", "resolve")])
        a, b = q[0], q[2]
        self.assertEqual((a.due, a.stage, a.wrong), (TODAY - dt.timedelta(days=2), 0, 2))
        self.assertTrue(a.is_due(TODAY))
        self.assertEqual(b.due, TODAY + dt.timedelta(days=2))
        self.assertFalse(b.is_due(TODAY))
        self.assertEqual(state.get("resolve")["2100A"], {"stage": 0, "due": "2026-10-04", "done": []})
        self.assertNotIn("2100C", state.get("resolve"))                     # only 1 failed attempt
        self.assertNotIn("2100D", state.get("resolve"))                     # solved too long ago

    def test_auto_complete_and_retire(self):
        # First AC 20 days ago; re-solved 15 and 5 days ago.
        subs = hard_won("2100A", 20, extra_acs=(15, 5))
        state = temp_state()
        q = retry_queue(make_snapshot(submissions=subs), state, today=TODAY)
        entry = state.get("resolve")["2100A"]
        self.assertEqual(entry["stage"], 2)
        self.assertEqual(entry["done"], [(TODAY - dt.timedelta(days=15)).isoformat(),
                                         (TODAY - dt.timedelta(days=5)).isoformat()])
        # stage 1 was due at first+10 (10 days ago) but never sooner than 7 days after the late
        # first re-solve (8 days ago); stage 2: max(first+30, 5 days ago + 20) = 15 days from now.
        self.assertEqual(entry["due"], (TODAY + dt.timedelta(days=15)).isoformat())
        self.assertEqual(q[0].stage, 2)
        self.assertFalse(q[0].is_due(TODAY))
        # The third re-solve retires it, and it isn't scheduled again.
        later = make_snapshot(submissions=subs + [sub("2100A", "OK", ts(-16))], now=NOW + 17 * 86400)
        self.assertEqual(retry_queue(later, state), [])
        self.assertEqual(state.get("resolve")["2100A"]["due"], None)
        self.assertEqual(retry_queue(later, state), [])

    def test_mark_resolved(self):
        snap = make_snapshot(submissions=hard_won("2100A", 5) + [sub("2100E", "WRONG_ANSWER", ts(1))])
        state = temp_state()
        nxt = mark_resolved(snap, state, "2100A")
        self.assertEqual((nxt.stage, nxt.due), (1, TODAY + dt.timedelta(days=7)))
        self.assertEqual(state.get("resolve")["2100A"]["done"], [TODAY.isoformat()])
        with self.assertRaisesRegex(DojoError, "already recorded"):
            mark_resolved(snap, state, "2100A")
        with self.assertRaisesRegex(DojoError, "isn't solved yet"):
            mark_resolved(snap, state, "2100E")
        with self.assertRaisesRegex(DojoError, "no submissions"):
            mark_resolved(snap, state, "2999A")
        nxt = mark_resolved(snap, state, "2100A", today=TODAY + dt.timedelta(days=8))
        # max(first AC + 30 = today + 25, this one + 20 days = today + 28)
        self.assertEqual((nxt.stage, nxt.due), (2, TODAY + dt.timedelta(days=28)))
        self.assertIsNone(mark_resolved(snap, state, "2100A", today=TODAY + dt.timedelta(days=30)))
        with self.assertRaisesRegex(DojoError, "already done"):
            mark_resolved(snap, state, "2100A", today=TODAY + dt.timedelta(days=31))

    def test_corrupt_schedule_is_rebuilt(self):
        state = temp_state()
        state.set("resolve", {"2100A": {"stage": "x"}, "2999A": "junk"})
        q = retry_queue(make_snapshot(submissions=hard_won("2100A", 5)), state)
        self.assertEqual(q[0].stage, 0)
        self.assertEqual(state.get("resolve")["2100A"]["stage"], 0)


class CommandTest(unittest.TestCase):
    def test_today_same_all_day(self):
        snap = plan_snap()
        with TempHome() as home:
            code, out1, err = run_cli(["today", "--json"], snap=snap, home=home)
            self.assertEqual(code, 0, err)
            code, out2, _ = run_cli(["today", "--json"], snap=plan_snap(problems=pool(3000)), home=home)
            doc = json.loads(out1)
            self.assertEqual([i["key"] for i in doc["items"]], [i["key"] for i in json.loads(out2)["items"]])
            self.assertEqual((doc["day"], doc["done"], doc["total"]), ("2026-10-06", 0, 4))
            self.assertNotIn("tags", doc["items"][0])
            code, out, _ = run_cli(["today", "--tags"], snap=snap, home=home)
            self.assertIn("in Java: dojo new", out)
            self.assertIn("0/4 done", out)
            code, out, _ = run_cli(["today", "--reroll", "--json"], snap=snap, home=home)
            self.assertEqual(json.loads(out)["rerolls"], 1)

    def test_today_dates(self):
        code, _, err = run_cli(["today", "--date", "2026-10-07"], snap=plan_snap())
        self.assertEqual(code, 1)
        self.assertIn("hasn't come yet", err)
        code, _, err = run_cli(["today", "--date", "2026-10-01"], snap=plan_snap())
        self.assertIn("no plan for Thu 01 Oct", err)
        code, _, err = run_cli(["today", "--date", "yesterday"], snap=plan_snap())
        self.assertIn("YYYY-MM-DD", err)

    def test_skip_command(self):
        snap = plan_snap()
        with TempHome() as home:
            first = json.loads(run_cli(["today", "--json"], snap=snap, home=home)[1])["items"][1]["key"]
            code, out, err = run_cli(["skip", first, "--reason", "boring"], snap=snap, home=home)
            self.assertEqual(code, 0, err)
            self.assertIn(f"Skipped {first}", out)
            items = json.loads(run_cli(["today", "--json"], snap=snap, home=home)[1])["items"]
            self.assertNotIn(first, [i["key"] for i in items])

    def test_upsolve_command(self):
        snap = UpsolveTest()
        snap.setUp()
        code, out, err = run_cli(["upsolve", "--json"], snap=snap.snap)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)[0]["key"], "1999A")
        code, out, _ = run_cli(["upsolve"], snap=snap.snap)
        self.assertIn("tried in contest", out)
        code, out, _ = run_cli(["upsolve"], snap=make_snapshot())
        self.assertIn("haven't taken part in a contest", out)

    def test_retry_command(self):
        snap = make_snapshot(submissions=hard_won("2100A", 5) + [sub("2100E", "WRONG_ANSWER", ts(1))])
        with TempHome() as home:
            code, out, err = run_cli(["retry"], snap=snap, home=home)
            self.assertEqual(code, 0, err)
            self.assertIn("RE-SOLVE FROM SCRATCH · 1 DUE", out)
            self.assertIn("STILL UNSOLVED · 1", out)
            code, out, _ = run_cli(["retry", "--done", "2100a"], snap=snap, home=home)
            self.assertIn("Recorded re-solve 1/3", out)
            rows = json.loads(run_cli(["retry", "--json", "--all"], snap=snap, home=home)[1])
            self.assertEqual([(r["key"], r["kind"], r["stage"]) for r in rows],
                             [("2100E", "unsolved", None), ("2100A", "resolve", 1)])
            code, _, err = run_cli(["retry", "--done", "bogus"], snap=snap, home=home)
            self.assertEqual(code, 1)


class RenderTest(unittest.TestCase):
    def test_render_plan(self):
        snap = plan_snap()
        plan = build(snap, java_day=True)
        term, _ = capture_term(100)
        text = recommend.render_plan(plan, snap, term, show_tags=True)
        self.assertTrue(text.startswith("Tue 06 Oct · comfort 900 · 0/4 done"))
        self.assertIn("warm-up", text)
        compact = recommend.render_plan(plan, snap, term, compact=True)
        self.assertEqual(len(compact.splitlines()), 4)
        empty = recommend.render_plan(build(make_snapshot()), make_snapshot(), term)
        self.assertIn("nothing to suggest", empty)


if __name__ == "__main__":
    unittest.main()
