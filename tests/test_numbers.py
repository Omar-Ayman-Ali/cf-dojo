import random
import unittest
from fractions import Fraction

from dojo.drill import core
from dojo.drill import numbers as nb
from tests.fixtures import run_cli

SEEDS = range(300)


class BaseConversionTest(unittest.TestCase):
    def test_integer_round_trip(self):
        rng = random.Random(2)
        for base in range(2, 17):
            for v in list(range(0, 300)) + [rng.randrange(1 << 40) for _ in range(50)]:
                digits = nb.int_digits(v, base)
                self.assertEqual(nb.value_of(digits, base), v)
                self.assertEqual(int(digits, base), v)

    def test_fraction_round_trip(self):
        rng = random.Random(3)
        for _ in range(500):
            v = rng.randrange(1000) + Fraction(rng.randrange(1 << 8), 1 << 8)
            for base in (2, 8, 16):                         # powers of 2 terminate
                e = nb.expand(v, base)
                self.assertTrue(e.exact)
                self.assertEqual(nb.value_of(str(e), base), v)
            e = nb.expand(v, 10)
            self.assertTrue(e.exact)
            self.assertEqual(nb.value_of(str(e), 10), v)

    def test_known_values(self):
        self.assertEqual(nb.to_base(Fraction(85, 8), 2), "1010.101")       # 10.625
        self.assertEqual(nb.to_base(255, 16), "FF")
        self.assertEqual(nb.to_base(Fraction(1, 10), 2), "0.0(0011)")       # repeating block
        self.assertEqual(nb.value_of("1f", 16), 31)
        with self.assertRaises(ValueError):
            nb.value_of("12", 2)

    def test_read_numeral(self):
        self.assertEqual(nb.read_numeral("0x1F", 16)[0], 31)
        self.assertEqual(nb.read_numeral("1f", 16)[0], 31)
        self.assertEqual(nb.read_numeral("0b1010_1010", 2)[0], 170)
        self.assertEqual(nb.read_numeral("1010 1010", 2)[0], 170)
        self.assertEqual(nb.read_numeral("0o17", 8)[0], 15)
        self.assertEqual(nb.read_numeral("(2D)16", 16)[0], 45)
        with self.assertRaises(ValueError):
            nb.read_numeral("0x1F", 2)                       # wrong prefix for the question
        with self.assertRaises(ValueError):
            nb.read_numeral("(2D)16", 10)

    def test_generated_questions(self):
        topic = core.load_topics()["base"]
        for level in (1, 2, 3):
            for seed in SEEDS:
                q = topic.generate(random.Random(seed), level)
                self.assertTrue(q.check(q.answer).ok, (level, seed, q.prompt, q.answer))
                self.assertTrue(q.check(" " + q.answer.lower() + " ").ok)
                src = next(b for b, name in nb.NAMES.items() if f"the {name} number" in q.prompt)
                dst = next(b for b, name in nb.NAMES.items() if q.prompt.rstrip(".").split(" to ")[-1] == name)
                shown = q.prompt.split(" number ", 1)[1].split(" to ", 1)[0]
                value = nb.value_of(shown, src)
                self.assertEqual(nb.value_of(q.answer, dst), value)      # the answer is the same number
                wrong = nb.to_base(value + 1, dst)
                self.assertFalse(q.check(wrong).ok)
                if level == 1:
                    self.assertIn((src, dst), [(10, 2), (2, 10)])
                if level == 3:
                    self.assertIn(".", q.answer)

    def test_common_slips_get_feedback(self):
        q = core.load_topics()["base"].solve("12 to 2")             # 1100
        v = q.check("0011")
        self.assertFalse(v.ok)
        self.assertIn("top-down", v.message)
        q = core.load_topics()["base"].solve("10.625 to 2")
        self.assertTrue(q.check("1010.101").ok)
        self.assertTrue(q.check("1010.1010").ok)

    def test_solve_syntax(self):
        t = core.load_topics()["base"]
        self.assertEqual(t.solve("255 to 16").answer, "FF")
        self.assertEqual(t.solve("0x1F to 2").answer, "11111")
        self.assertEqual(t.solve("101.101 b2 to 10").answer, "5.625")
        self.assertEqual(t.solve("7B hex to oct").answer, "173")
        q = t.solve("0.1 to 2")
        self.assertTrue(q.check("0.0001").ok)                       # truncated
        self.assertTrue(q.check("0.0010").ok)                       # rounded up
        self.assertTrue(q.check("0.0").retry)
        for bad in ("255", "1F to 2", "-5 to 2", "255 to 1", "12 to 10"):
            with self.assertRaises(ValueError, msg=bad):
                t.solve(bad)

    def test_solution_methods(self):
        t = core.load_topics()["base"]
        self.assertIn("remainder", t.solve("82 to 2").solution)
        self.assertIn("2⁻¹", t.solve("101.101 b2 to 10").solution)
        sol = t.solve("0b11010110 to 16").solution
        self.assertIn("1101 0110", sol)
        self.assertIn("integer part", t.solve("10.625 to 2").solution)


class SignedTest(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        for n in range(2, 11):
            lo, hi = nb.tc_range(n)
            for v in range(lo, hi + 1):
                bits = nb.tc_encode(v, n)
                self.assertEqual(len(bits), n)
                self.assertEqual(nb.tc_decode(bits), v)
                if v > lo:
                    self.assertEqual(nb.sm_decode(nb.sm_encode(v, n)), v)
                    self.assertEqual(nb.ones_decode(nb.ones_encode(v, n)), v)
            with self.assertRaises(ValueError):
                nb.tc_encode(hi + 1, n)
        self.assertEqual(nb.tc_encode(-45, 8), "11010011")
        self.assertEqual(nb.sm_encode(-45, 8), "10101101")
        self.assertEqual(nb.ones_encode(-45, 8), "11010010")

    def test_overflow_rule_matches_range_exhaustively(self):
        n = 5
        lo, hi = nb.tc_range(n)
        for a in range(lo, hi + 1):
            for b in range(lo, hi + 1):
                for op in "+-":
                    r = nb.arith(a, b, op, n)
                    true = a + b if op == "+" else a - b
                    self.assertEqual(r.overflow, not lo <= true <= hi, (a, op, b))
                    self.assertEqual(nb.tc_decode(r.result), (true - lo) % (1 << n) + lo, (a, op, b))

    def test_carry_row_lines_up_with_the_bits(self):
        lines, total, carries = nb.addition_table("01100100", "11100101", 0, ("A", "-B"))
        carry, top = lines[0], lines[1]
        self.assertEqual(len(carry.rstrip()), len(top.split("   (")[0].rstrip()))
        self.assertEqual(carry.split()[-1], "111001000")        # carry out, then the carry into each bit
        self.assertEqual(total, "01001001")

    def test_generated_questions(self):
        topic = core.load_topics()["twos"]
        kinds = set()
        for level in (1, 2, 3):
            for seed in SEEDS:
                q = topic.generate(random.Random(seed), level)
                self.assertTrue(q.check(q.answer).ok, (level, seed, q.prompt, q.answer))
                self.assertTrue(q.solution and q.hint)
                kinds.add(q.prompt.split()[0])
                if q.expect.endswith("-bit binary"):
                    n = int(q.expect.split("-")[0])
                    bits = q.answer.replace(" ", "")
                    self.assertEqual(len(bits), n)
                    self.assertTrue(q.check(bits[:-1]).retry)          # wrong width: ask again
                    flipped = bits[:-1] + ("1" if bits[-1] == "0" else "0")
                    self.assertFalse(q.check(flipped).ok)
        self.assertTrue({"Write", "What", "Compute", "In"} <= kinds)

    def test_slip_messages(self):
        t = core.load_topics()["twos"]
        q = t.solve("-45 bits=8")
        self.assertIn("one's complement", q.check("11010010").message)
        self.assertIn("sign-magnitude", q.check("10101101").message)
        q = t.solve("11010110 bits=8")
        self.assertEqual(q.answer, "-42")
        self.assertIn("unsigned", q.check("214").message)
        q = t.solve("100 - 27 bits=8")
        self.assertIn("didn't add 1", q.check(nb.ripple_add("01100100", nb.invert("00011011"))[0]).message)

    def test_arith_answers_with_overflow_claim(self):
        q = core.load_topics()["twos"].solve("100 + 50 bits=8")
        bits = nb.arith(100, 50, "+", 8).result
        self.assertTrue(q.check(bits).ok)
        self.assertTrue(q.check(bits + " overflow").ok)
        self.assertTrue(q.check(bits + " yes").ok)
        self.assertTrue(q.check(q.answer).ok)
        v = q.check(bits + " no overflow")
        self.assertFalse(v.ok)
        self.assertIn("does overflow", v.message)

    def test_range(self):
        q = core.load_topics()["twos"].range_question(8, "twos")
        self.assertTrue(q.check("-128 to 127").ok)
        self.assertTrue(q.check("-128, 127").ok)
        self.assertIn("sign-magnitude", q.check("-127 127").message)
        self.assertTrue(q.check("127").retry)
        q = core.load_topics()["twos"].range_question(8, "sm")
        self.assertTrue(q.check("-127 … 127").ok)

    def test_solve_syntax(self):
        t = core.load_topics()["twos"]
        self.assertEqual(t.solve("-45 bits=8").answer, "11010011")
        self.assertEqual(t.solve("11010110 bits=8").answer, "-42")
        self.assertEqual(t.solve("-45 + 23 bits=8").answer, "11101010  (no overflow)")
        self.assertEqual(t.solve("100 - 27 bits=8").answer, "01001001  (no overflow)")
        self.assertEqual(t.solve("100 + 50 bits=8").answer, "10010110  (overflow)")
        self.assertEqual(t.solve("-300").answer, "1111 1110 1101 0100")            # 16 bits by default
        for bad in ("abc", "5 bits=3", "1 + 2 + 3", "99999999999999999999999", "-45 + bits=8"):
            with self.assertRaises(ValueError, msg=bad):
                t.solve(bad)


class CliTest(unittest.TestCase):
    def test_solve_commands(self):
        code, out, _ = run_cli(["solve", "base", "255", "to", "16"])
        self.assertEqual(code, 0)
        self.assertIn("FF", out)
        code, out, _ = run_cli(["solve", "twos", "-45", "bits=8", "--check", "11010011"])
        self.assertEqual(code, 0)
        code, out, _ = run_cli(["solve", "twos", "-45", "bits=8", "--check", "11010010"])
        self.assertEqual(code, 1)
        self.assertIn("one's complement", out)
        code, out, err = run_cli(["solve", "twos", "-45", "bits=8", "--check", "2"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
