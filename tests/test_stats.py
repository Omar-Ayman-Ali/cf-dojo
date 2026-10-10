import random
import re
import unittest
from decimal import Decimal
from fractions import Fraction

from dojo.drill import core
from dojo.drill import stats as st
from tests.fixtures import run_cli

SEEDS = range(300)
F = Fraction


def plus(answer: str, delta: str) -> str:
    """The answer shifted by delta, keeping a trailing % or °."""
    m = re.fullmatch(r"(-?[\d.]+)([%°]?)", answer)
    return str(Decimal(m.group(1)) + Decimal(delta)) + m.group(2) if m else answer


class FrequencyTest(unittest.TestCase):
    # Lecture example: blood types of n = 28 people.
    DATA = ["A"] * 9 + ["B"] * 5 + ["AB"] * 2 + ["O"] * 12

    def test_lecture_table(self):
        t = st.freq_table(self.DATA, ["A", "B", "AB", "O"])
        self.assertEqual(t.freq, [9, 5, 2, 12])
        self.assertEqual(t.n, 28)
        self.assertEqual(core.fmt_number(t.rel(0)), "32.14")
        self.assertEqual(core.fmt_number(t.cum(2)), "57.14")
        self.assertEqual(t.cum(3), 100)
        self.assertEqual(core.fmt_number(t.angle(3)), "154.29")
        self.assertEqual(sum(t.angle(i) for i in range(4)), 360)
        lines = t.lines(angle=True)
        self.assertEqual([c.strip() for c in lines[0].split("│")],
                         ["Class", "Frequency", "Relative %", "Cumulative %", "Angle"])

    def test_questions_grade_percentages_and_angles(self):
        t = st.freq_table(self.DATA, ["A", "B", "AB", "O"])
        q = st.Frequency.question(self.DATA, t, "rel", 0, "blood types")
        for ok in ("32.14", "32.14%", "32.1429", "32.143"):
            self.assertTrue(q.check(ok).ok, ok)
        self.assertFalse(q.check("32.15").ok)
        v = q.check("0.3214")
        self.assertTrue(v.retry)
        self.assertIn("percentage", v.message)
        q = st.Frequency.question(self.DATA, t, "angle", 3, "blood types")
        self.assertTrue(q.check("154.29°").ok)
        self.assertTrue(q.check("154.29 degrees").ok)
        q = st.Frequency.question(self.DATA, t, "freq", 1, "blood types")
        self.assertTrue(q.check("5").ok)
        self.assertFalse(q.check("5.4").ok)
        q = st.Frequency.question(self.DATA, t, "cum", 2, "blood types")
        self.assertIn("A, B, AB, O", q.prompt)
        self.assertEqual(q.answer, "57.14%")

    def test_solve(self):
        t = core.load_topics()["freq"]
        q = t.solve("A B O AB A O O B class=O what=angle")
        self.assertEqual(q.answer, "135°")
        q = t.solve("0 1 1 2 2 2 3 class=2 what=cum")
        self.assertEqual(q.answer, "85.71%")
        q = t.solve("A B O AB A O")
        self.assertIn("Cumulative %", q.solution)
        self.assertTrue(q.check("12").retry)
        for bad in ("A", "A B class=Z", "A B what=median"):
            with self.assertRaises(ValueError, msg=bad):
                t.solve(bad)


class CenterTest(unittest.TestCase):
    def test_basics(self):
        xs = [F(x) for x in (4, 8, 6, 5, 3, 4)]
        self.assertEqual(st.median_of(xs), F(9, 2))
        self.assertEqual(st.median_of(xs[:5]), 5)
        self.assertEqual(st.modes_of(xs), [4])
        self.assertEqual(st.modes_of([F(1), F(2)]), [])
        self.assertEqual(st.modes_of([F(1), F(1), F(2), F(2)]), [1, 2])

    def test_multimodal_answers_need_every_mode(self):
        q = core.load_topics()["center"].solve("1 1 2 2 3 mode")
        self.assertTrue(q.check("1, 2").ok)
        self.assertTrue(q.check("2 1").ok)
        self.assertIn("more modes", q.check("1").message)
        q = core.load_topics()["center"].solve("1 2 3 mode")
        self.assertTrue(q.check("none").ok)

    def test_generated_mode_questions_are_unimodal(self):
        topic = core.load_topics()["center"]
        for level in (1, 2):
            for seed in SEEDS:
                q = topic.generate(random.Random(seed), level)
                if q.prompt.endswith("Find the mode."):
                    self.assertNotIn(",", q.answer)
                    self.assertNotEqual(q.answer, "none")

    def test_frequency_table(self):
        xs, fs = [F(1), F(2), F(3)], [4, 5, 6]
        q = st.Center.table_question(xs, fs, "mean")
        self.assertEqual(q.answer, "2.13")                       # 32 / 15
        self.assertTrue(q.check("2.133").ok)
        self.assertFalse(q.check("2").ok)
        self.assertEqual(st.Center.table_question(xs, fs, "median").answer, "2")
        self.assertEqual(st.Center.table_question(xs, fs, "mode").answer, "3")

    def test_solve(self):
        t = core.load_topics()["center"]
        q = t.solve("4 8 6 5 3 4")
        self.assertTrue(q.check("mean=5 median=4.5 mode=4").ok)
        self.assertFalse(q.check("mean=5 median=5").ok)
        self.assertTrue(q.check("5").retry)
        self.assertEqual(t.solve("1:4 2:5 3:6").answer, "2.13")
        self.assertEqual(t.solve("4 8 6 median").answer, "6")
        with self.assertRaises(ValueError):
            t.solve("1:4 2:4 mode")
        with self.assertRaises(ValueError):
            t.solve("x y z")


class SpreadTest(unittest.TestCase):
    XS = [F(x) for x in (4, 8, 6, 5, 3)]

    def test_population_and_sample(self):
        pop, smp = st.Spread(self.XS, False), st.Spread(self.XS, True)
        self.assertEqual(pop.mean, F(26, 5))
        self.assertEqual(pop.ss, F(74, 5))                       # 14.8
        self.assertEqual(pop.var, F(74, 25))                     # 2.96
        self.assertEqual(smp.var, F(37, 10))                     # 3.7
        self.assertAlmostEqual(float(smp.sd), 1.9235, places=4)
        self.assertEqual(pop.range, 5)
        self.assertEqual(st.Spread([F(1), F(3)], False).sd, 1)   # exact square root

    def test_question_says_which_and_grades_the_slip(self):
        q = st.Variability.question(st.Spread(self.XS, True), "var")
        self.assertIn("sample", q.prompt)
        self.assertIn("n − 1", q.prompt)
        self.assertTrue(q.check("3.7").ok)
        self.assertIn("divides by N", q.check("2.96").message)
        q = st.Variability.question(st.Spread(self.XS, False), "sd")
        self.assertIn("population", q.prompt)
        self.assertTrue(q.check("1.72").ok)
        self.assertIn("variance", q.check("2.96").message)
        self.assertIn("n − 1", q.check("1.92").message)

    def test_ss_table_in_solution(self):
        sol = st.Variability.question(st.Spread(self.XS, True), "sd").solution
        self.assertIn("X − X̄", sol)
        self.assertIn("SS = 14.8", sol)
        self.assertIn("s² = SS / (n − 1) = 14.8 / 4 = 3.7", sol)

    def test_generated_data_is_clean(self):
        topic = core.load_topics()["spread"]
        for level in (1, 2, 3):
            for seed in range(100):
                q = topic.generate(random.Random(seed), level)
                data = [F(x) for x in q.prompt.splitlines()[1].split()]
                mean = sum(data) / len(data)
                self.assertEqual((mean * (1 if level <= 2 else 10)).denominator, 1)
                self.assertTrue(("sample" in q.prompt) != ("population" in q.prompt))

    def test_solve(self):
        t = core.load_topics()["spread"]
        self.assertEqual(t.solve("4 8 6 5 3 sample").answer, "1.92")
        self.assertEqual(t.solve("4 8 6 5 3 population var").answer, "2.96")
        self.assertEqual(t.solve("4, 8, 6, 5, 3 sample ss").answer, "14.8")
        self.assertEqual(t.solve("4 8 6 5 3 pop range").answer, "5")
        with self.assertRaises(ValueError):
            t.solve("4 8 6 5 3")                                 # must say which
        with self.assertRaises(ValueError):
            t.solve("4 sample")


class ZScoreTest(unittest.TestCase):
    def test_z_and_raw(self):
        t = core.load_topics()["zscore"]
        q = t.solve("x=72 mean=65 sd=5")
        self.assertEqual(q.answer, "1.4")
        self.assertTrue(q.check("1.40").ok)
        q = t.solve("x=55 mean=75 sd=12")
        self.assertEqual(q.answer, "-1.67")
        self.assertIn("sign", q.check("1.67").message)
        self.assertEqual(t.solve("z=-1.5 mean=65 sd=5").answer, "57.5")

    def test_compare(self):
        q = core.load_topics()["zscore"].solve("x=72 mean=65 sd=5 ; x=80 mean=74 sd=8")
        self.assertEqual(q.answer, "Score 1")
        self.assertTrue(q.check("1").ok)
        self.assertTrue(q.check("first").ok)
        self.assertFalse(q.check("score 2").ok)
        self.assertTrue(q.check("dunno").retry)

    def test_generated_comparisons_are_never_close(self):
        topic = core.load_topics()["zscore"]
        for seed in SEEDS:
            q = topic.generate(random.Random(seed), 3)
            if "which score is better" not in q.prompt:
                continue
            nums = [F(x) for x in re.findall(r"\d+", q.prompt)]
            x1, m1, s1, x2, m2, s2 = nums
            self.assertGreaterEqual(abs((x1 - m1) / s1 - (x2 - m2) / s2), F(1, 10))

    def test_solve_errors(self):
        t = core.load_topics()["zscore"]
        for bad in ("x=1", "x=1 mean=2 sd=0", "x=1 z=2 mean=1 sd=1", "mean=1 sd=1", "q=1 mean=1 sd=1"):
            with self.assertRaises(ValueError, msg=bad):
                t.solve(bad)


class GeneratedTest(unittest.TestCase):
    def test_own_answers_pass_and_neighbours_fail(self):
        topics = core.load_topics()
        for key in ("freq", "center", "spread", "zscore"):
            for level in (1, 2, 3):
                for seed in SEEDS:
                    q = topics[key].generate(random.Random(seed), level)
                    self.assertTrue(q.check(q.answer).ok, (key, level, seed, q.prompt, q.answer))
                    self.assertTrue(q.prompt and q.solution and q.hint and q.expect)
                    if re.fullmatch(r"-?[\d.]+[%°]?", q.answer):
                        self.assertFalse(q.check(plus(q.answer, "0.02")).ok, (key, level, seed, q.answer))
                        self.assertFalse(q.check(plus(q.answer, "1")).ok, (key, level, seed, q.answer))

    def test_registered(self):
        topics = core.load_topics()
        for key in ("freq", "center", "spread", "zscore"):
            self.assertEqual(topics[key].course, "CIS 208")


class CliTest(unittest.TestCase):
    def test_solve(self):
        code, out, _ = run_cli(["solve", "spread", "4", "8", "6", "5", "3", "sample"])
        self.assertEqual(code, 0)
        self.assertIn("1.92", out)
        code, out, _ = run_cli(["solve", "zscore", "x=72", "mean=65", "sd=5", "--check", "1.4"])
        self.assertEqual(code, 0)
        code, out, err = run_cli(["solve", "spread", "4", "8"])
        self.assertNotEqual(code, 0)
        self.assertIn("sample", out + err)


if __name__ == "__main__":
    unittest.main()
