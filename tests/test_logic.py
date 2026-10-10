import itertools
import random
import unittest

from dojo.drill import boolexpr as bx
from dojo.drill import core, logic
from dojo.drill.boolexpr import AND, IFF, IMP, NOT, OR, XOR, Implicant, ParseError, Var, parse
from tests.fixtures import capture_term, run_cli, temp_state

A, B, C, D = (Var(v) for v in "ABCD")
p, q, r = (Var(v) for v in "pqr")
SEEDS = range(150)


def brute_cost(n, on, dc=()):
    """Cheapest cover by brute force over subsets of the prime implicants: (terms, literals)."""
    if not on:
        return (0, 0)
    primes = bx.prime_implicants(n, on, dc)
    need = sum(1 << m for m in on)
    masks = [sum(1 << m for m in pi.minterms()) & need for pi in primes]
    for k in range(1, len(primes) + 1):
        best = None
        for combo in itertools.combinations(range(len(primes)), k):
            cov = 0
            for i in combo:
                cov |= masks[i]
            if cov == need:
                lits = sum(primes[i].literals for i in combo)
                best = lits if best is None else min(best, lits)
        if best is not None:
            return (k, best)
    raise AssertionError("no cover")


class MinimizeTest(unittest.TestCase):
    def check_function(self, n, on, dc=()):
        a = bx.analyze(n, on, dc)
        covered = 0
        for imp in a.cover:
            for m in imp.minterms():
                covered |= 1 << m
        on_mask, dc_mask = sum(1 << m for m in on), sum(1 << m for m in dc)
        self.assertEqual(covered & ~dc_mask, on_mask, (n, on, dc))          # equal on the care set
        self.assertEqual(a.cost, brute_cost(n, on, dc), (n, on, dc))
        for alt in a.alternatives:
            self.assertEqual((len(alt), sum(i.literals for i in alt)), a.cost)
        for e in a.essential:
            self.assertIn(e, a.cover)

    def test_every_3_variable_function(self):
        for mask in range(256):
            self.check_function(3, [m for m in range(8) if mask >> m & 1])

    def test_every_4_variable_function_up_to_6_minterms(self):
        for k in range(7):
            for on in itertools.combinations(range(16), k):
                self.check_function(4, on)

    def test_random_4_and_5_variable_functions_with_dont_cares(self):
        rng = random.Random(203)
        for _ in range(600):
            cells = list(range(16))
            rng.shuffle(cells)
            k, d = rng.randint(7, 14), rng.randint(0, 4)
            self.check_function(4, sorted(cells[:k]), sorted(cells[k:k + d]))
        for _ in range(60):
            cells = list(range(32))
            rng.shuffle(cells)
            k, d = rng.randint(4, 14), rng.randint(0, 4)
            self.check_function(5, sorted(cells[:k]), sorted(cells[k:k + d]))

    def test_deterministic_and_known_answers(self):
        self.assertEqual(bx.sop_str(bx.minimize(4, [0, 2, 5, 7, 8, 10, 13, 15])), "B'D' + BD")
        self.assertEqual(bx.minimize(4, [1, 3, 4, 6]), bx.minimize(4, [6, 4, 3, 1]))
        self.assertEqual(bx.sop_str(bx.minimize(3, range(8))), "1")
        self.assertEqual(bx.sop_str(bx.minimize(3, [])), "0")
        # cyclic core: no essential primes, Petrick picks 3 terms
        a = bx.analyze(3, [0, 1, 2, 5, 6, 7])
        self.assertEqual(a.essential, [])
        self.assertEqual(a.cost, (3, 6))
        self.assertTrue(a.alternatives)

    def test_minimal_pos_is_the_complement(self):
        for mask in range(256):
            on = [m for m in range(8) if mask >> m & 1]
            groups = bx.minimal_pos(3, on)
            text = bx.pos_str(groups)
            self.assertEqual(bx.minterms(parse(text), "ABC") if text not in ("0", "1") else
                             (list(range(8)) if text == "1" else []), on, text)

    def test_validation(self):
        with self.assertRaises(ValueError):
            bx.minimize(3, [8])
        with self.assertRaises(ValueError):
            bx.minimize(3, [1], [1])


class ParseTest(unittest.TestCase):
    def test_design_notation(self):
        self.assertEqual(parse("AB'C"), AND(A, NOT(B), C))
        self.assertEqual(parse("A(B + C)'"), AND(A, NOT(OR(B, C))))
        self.assertEqual(parse("(A + B)(C + D)"), AND(OR(A, B), OR(C, D)))
        self.assertEqual(parse("A''"), NOT(NOT(A)))
        self.assertEqual(parse("F = AB + C"), OR(AND(A, B), C))
        self.assertEqual(parse("F(A,B,C) = A"), A)

    def test_discrete_notation(self):
        self.assertEqual(parse("~p & (q -> r)"), AND(NOT(p), IMP(q, r)))
        self.assertEqual(parse("¬p ∧ (q → r)"), parse("not p and (q implies r)"))
        self.assertEqual(parse("p -> q -> r"), IMP(p, IMP(q, r)))          # right-associative
        self.assertEqual(parse("p <-> q"), IFF(p, q))
        self.assertEqual(parse("p ↔ q"), parse("p iff q"))
        self.assertEqual(parse("p xor q"), XOR(p, q))
        self.assertEqual(parse("p & T"), AND(p, bx.TRUE))

    def test_precedence(self):
        # NOT > AND > XOR > OR > IMPLIES > IFF
        self.assertEqual(parse("A + B C"), OR(A, AND(B, C)))
        self.assertEqual(parse("A ⊕ B + C"), OR(XOR(A, B), C))
        self.assertEqual(parse("A B ⊕ C"), XOR(AND(A, B), C))
        self.assertEqual(parse("p | q -> r"), IMP(OR(p, q), r))
        self.assertEqual(parse("p -> q <-> r"), IFF(IMP(p, q), r))
        self.assertEqual(parse("~p & q"), AND(NOT(p), q))

    def test_errors_have_messages_and_positions(self):
        with self.assertRaises(ParseError) as cm:
            parse("A ^ B")
        self.assertIn("ambiguous: write & for AND or xor for XOR", str(cm.exception))
        self.assertEqual(cm.exception.pos, 2)
        for bad in ["", "A +", "(A + B", "A + B)", "pq", "p v q", "A @ B", "2", "()", "p q"]:
            with self.assertRaises(ParseError, msg=bad):
                parse(bad)

    def test_printing_round_trips(self):
        rng = random.Random(1)
        for i in range(400):
            names = "ABCD" if i % 2 else "pqrs"
            kinds = ["and", "or", "xor", "imp", "iff"]
            e = logic._random_expr(rng, names, rng.randint(0, 6), kinds, neg_leaf=0.4, neg_group=0.2)
            vs = sorted(e.vars())
            for style in ("design", "discrete"):
                text = e.to_str(style)
                self.assertEqual(bx.truth_mask(parse(text), vs), bx.truth_mask(e, vs), (style, text))

    def test_tables_and_minterms(self):
        e = parse("AB' + A'(B + C)")
        self.assertEqual(bx.minterms(e, "ABC"), [1, 2, 3, 4, 5])
        tt = bx.truth_table(parse("p -> q"))
        self.assertEqual([v for _, v in tt], [True, True, False, True])     # FF FT TF TT
        self.assertEqual(bx.minterms(parse("A"), "ABC"), [4, 5, 6, 7])

    def test_sop_and_cost(self):
        self.assertTrue(bx.is_sop(parse("AB' + C")))
        self.assertTrue(bx.is_sop(parse("A")))
        self.assertFalse(bx.is_sop(parse("A(B + C)")))
        self.assertFalse(bx.is_sop(parse("(AB)'")))
        self.assertFalse(bx.is_sop(parse("A ⊕ B")))
        self.assertEqual(bx.cost(parse("AB' + C")), (2, 3))
        self.assertEqual(bx.cost(parse("0")), (0, 0))
        self.assertEqual(bx.cost(parse("1")), (1, 0))
        self.assertEqual(Implicant(4, 0b0101, 0b0010).to_str(), "A'BD")


def all_levels(topic):
    for level in range(1, topic.levels + 1):
        for seed in SEEDS:
            yield level, seed, topic.generate(random.Random(seed), level)


class GeneratedQuestionsTest(unittest.TestCase):
    def setUp(self):
        self.topics = core.load_topics()

    def test_every_logic_topic_registered(self):
        for key in ("truth", "equiv", "minterms", "kmap", "simplify"):
            self.assertIn(key, self.topics)
            self.assertIn(self.topics[key].course, ("CIS 203", "BSC 201"))

    def test_own_answers_pass_own_check(self):
        for key in ("truth", "equiv", "minterms", "kmap", "simplify"):
            for level, seed, q in all_levels(self.topics[key]):
                v = q.check(q.answer)
                self.assertTrue(v.ok, (key, level, seed, q.prompt, q.answer, v))
                self.assertTrue(q.prompt and q.solution and q.expect, (key, level, seed))

    def test_same_seed_same_question(self):
        for key in ("truth", "equiv", "minterms", "kmap", "simplify"):
            a = self.topics[key].generate(random.Random(9), 2)
            b = self.topics[key].generate(random.Random(9), 2)
            self.assertEqual((a.prompt, a.answer), (b.prompt, b.answer))

    def test_truth_answers_match_the_formula(self):
        for level, seed, q in all_levels(self.topics["truth"]):
            text = q.prompt.splitlines()[1].strip()
            e = parse(text)
            names = sorted(e.vars())
            mask = bx.truth_mask(e, names)
            if q.answer in ("tautology", "contradiction", "contingency"):
                self.assertEqual(q.answer, logic.classify_mask(mask, len(names)))
                wrong = {"tautology": "c", "contradiction": "t", "contingency": "t"}[q.answer]
                self.assertFalse(q.check(wrong).ok)
            else:
                rows = 1 << len(names)
                self.assertEqual(len(q.answer), rows)
                flipped = ("F" if q.answer[0] == "T" else "T") + q.answer[1:]
                v = q.check(flipped)
                self.assertFalse(v.ok)
                self.assertIn("row 1", v.message)
                self.assertTrue(q.check(q.answer[:-1]).retry)

    def test_equiv_answers_match_truth_tables(self):
        seen = set()
        for level, seed, q in all_levels(self.topics["equiv"]):
            lines = q.prompt.splitlines()
            a, b = parse(lines[1].split("=", 1)[1]), parse(lines[2].split("=", 1)[1])
            names = sorted(a.vars() | b.vars())
            same = bx.truth_mask(a, names) == bx.truth_mask(b, names)
            self.assertEqual(q.answer, "yes" if same else "no")
            self.assertFalse(q.check("no" if same else "yes").ok)
            if not same:
                self.assertIn("Counterexample", q.solution)
            seen.add(q.answer)
        self.assertEqual(seen, {"yes", "no"})

    def test_minterms_answers(self):
        for level, seed, q in all_levels(self.topics["minterms"]):
            head, expr = q.prompt.split(" = ", 1)
            names = head[head.index("(") + 1:head.index(")")].split(", ")
            want = bx.minterms(parse(expr), names)
            self.assertEqual(q.answer, ", ".join(map(str, want)))
            self.assertTrue(q.check("m(" + ",".join(map(str, reversed(want))) + ")").ok)
            self.assertFalse(q.check(" ".join(map(str, want[1:]))).ok)

    def test_kmap_and_simplify_answers_are_minimal_sops(self):
        for key in ("kmap", "simplify"):
            for level, seed, q in all_levels(self.topics[key]):
                e = parse(q.answer)
                self.assertTrue(bx.is_sop(e), q.answer)

    def test_kmap_levels(self):
        for level, seed, q in all_levels(self.topics["kmap"]):
            n = q.prompt.count(",", q.prompt.index("("), q.prompt.index(")")) + 1
            self.assertEqual(n, 3 if level == 1 else 4)
            self.assertEqual("d(" in q.prompt, level == 3)


class GradingTest(unittest.TestCase):
    def setUp(self):
        self.kmap = core.load_topics()["kmap"].solve("m(0,2,5,7,8,10,13,15) d(1)")

    def test_kmap_grading(self):
        check = self.kmap.check
        self.assertTrue(check("B'D' + BD").ok)
        self.assertTrue(check("BD + B'D'").ok)
        self.assertTrue(check("b'd' + bd").ok)                     # lower case is fine
        self.assertTrue(check("F = BD + B'D'").ok)
        v = check("B'D'")
        self.assertFalse(v.ok)
        self.assertIn("m5 = A'BC'D", v.message)
        v = check("(B ⊕ D)'")
        self.assertTrue(v.retry)
        self.assertIn("sum of products", v.message)
        v = check("B'D' + BD + A'B'C'D'")
        self.assertFalse(v.ok)
        self.assertIn("3 terms / 8 literals; minimum is 2 / 4", v.message)
        self.assertTrue(check("A + ").retry)
        self.assertTrue(check("BD + E").retry)

    def test_dont_care_may_go_either_way(self):
        q = core.load_topics()["kmap"].solve("m(0,1,2) d(5)")
        self.assertTrue(q.check("A'B' + A'C'").ok)               # leaves m5 at 0
        self.assertTrue(q.check("A'C' + B'C").ok)                # sets m5 to 1
        v = q.check("A'B'C' + A'B'C + A'BC'")
        self.assertFalse(v.ok)
        self.assertIn("minimum is 2 / 4", v.message)

    def test_truth_solve_accepts_word_or_column(self):
        q = core.load_topics()["truth"].solve("p -> q")
        self.assertTrue(q.check("contingency").ok)
        self.assertTrue(q.check("TFTT").ok)
        self.assertTrue(q.check("1 0 1 1").ok)
        self.assertFalse(q.check("tautology").ok)
        self.assertFalse(q.check("TTFT").ok)
        self.assertTrue(q.check("maybe").retry)

    def test_class_words(self):
        for word, want in [("t", "tautology"), ("Tautology", "tautology"), ("c", "contradiction"),
                           ("contingent", "contingency"), ("neither", "contingency")]:
            self.assertEqual(logic.read_class(word), want)
        with self.assertRaises(ValueError):
            logic.read_class("x")

    def test_minterms_reader(self):
        self.assertEqual(logic.read_minterms("Σm(1, 3, 6)", 3), {1, 3, 6})
        self.assertEqual(logic.read_minterms("m1 m3 m6", 3), {1, 3, 6})
        self.assertEqual(logic.read_minterms("1,3 6", 3), {1, 3, 6})
        with self.assertRaises(ValueError):
            logic.read_minterms("1, 9", 3)
        with self.assertRaises(ValueError):
            logic.read_minterms("A'B", 3)


class SolveTest(unittest.TestCase):
    def setUp(self):
        self.t = core.load_topics()

    def test_solve_syntax_from_the_design(self):
        self.assertEqual(self.t["kmap"].solve("m(0,2,5,7) d(1)").answer, "A'C' + AC")
        self.assertEqual(self.t["kmap"].solve("m(0,2,5,7) vars=WXYZ").answer, "W'X'Z' + W'XZ")
        self.assertEqual(self.t["kmap"].solve("AB + A'C + BC").answer, "A'C + AB")
        self.assertEqual(self.t["truth"].solve("(p -> q) & ~q -> ~p").answer, "tautology (TTTT)")
        self.assertEqual(self.t["equiv"].solve("p -> q ; ~q -> ~p").answer, "yes")
        self.assertEqual(self.t["equiv"].solve("p -> q ; q -> p").answer, "no")
        self.assertEqual(self.t["minterms"].solve("AB' + A'(B + C)").answer, "1, 2, 3, 4, 5")
        self.assertEqual(self.t["simplify"].solve("A'B'C + A'BC + AB'C + ABC").answer, "C")

    def test_solve_errors(self):
        for key, text in [("kmap", "m(1,3) d(3)"), ("kmap", "m(1,9) vars=ABC"), ("kmap", "m(a,b)"),
                          ("equiv", "p -> q"), ("truth", "p ^ q"), ("minterms", "AB vars=A"),
                          ("truth", "a & b & c & d & e & f")]:
            with self.assertRaises(ValueError, msg=(key, text)):
                self.t[key].solve(text)

    def test_kmap_solution_layout(self):
        sol = self.t["kmap"].solve("m(0,2,5,7,8,10,13,15) d(1)").solution.splitlines()
        i = next(k for k, line in enumerate(sol) if "AB\\CD" in line)
        self.assertEqual(sol[i].split(), ["AB\\CD", "00", "01", "11", "10"])
        self.assertEqual(sol[i + 1].split(), ["00", "1", "X", "0", "1"])
        self.assertEqual(sol[i + 3].split()[0], "11")                    # Gray-code row order
        self.assertTrue(any(line.startswith("Essential") for line in sol))
        self.assertTrue(any("Minimal SOP: F = B'D' + BD" in line for line in sol))

    def test_truth_table_rows_rosen_order(self):
        lines = logic.discrete_table([parse("p -> q")], "pq")
        body = [line.split() for line in lines[2:]]
        self.assertEqual([row[:2] for row in body], [["T", "T"], ["T", "F"], ["F", "T"], ["F", "F"]])
        self.assertEqual([row[-1] for row in body], ["T", "F", "T", "T"])


class CliTest(unittest.TestCase):
    def test_solve_check(self):
        code, out, _ = run_cli(["solve", "kmap", "m(0,2,5,7)", "d(1)", "--check", "A'C' + AC"])
        self.assertEqual(code, 0)
        self.assertIn("correct", out)
        code, out, _ = run_cli(["solve", "kmap", "m(0,2,5,7)", "d(1)", "--check", "A'C'"])
        self.assertEqual(code, 1)
        code, out, err = run_cli(["solve", "truth", "p ^ q"])
        self.assertNotEqual(code, 0)
        self.assertIn("ambiguous", out + err)

    def test_drill_session(self):
        # run_session directly: core.run_session binds input() at import time, so patching
        # builtins.input through run_cli doesn't reach it once dojo.drill.core is imported.
        topic = core.load_topics()["kmap"]
        q = topic.generate(random.Random(5), 2)
        feed = iter(["?", "(A", q.answer])
        term, buf = capture_term()
        res = core.run_session([topic], n=1, level=2, rng=random.Random(5), term=term, state=temp_state(),
                               input_fn=lambda prompt: next(feed))
        out = buf.getvalue()
        self.assertEqual((res.asked, res.correct), (1, 1))
        self.assertIn("hint:", out)
        self.assertIn("never closed", out)
        self.assertIn("correct", out)

if __name__ == "__main__":
    unittest.main()
