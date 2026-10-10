import io
import json
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from dojo import gen
from dojo.errors import DojoError
from dojo.run import cph, judge
from dojo.run.judge import compare
from dojo.run.lang import Program, build, find_main_class
from dojo.run.stress import stress
from tests.fixtures import TempHome, run_cli

HAVE_GXX = shutil.which("g++") is not None
HAVE_JAVA = shutil.which("javac") is not None and shutil.which("java") is not None


class Workspace:
    """A temp folder for solution files: with Workspace() as ws: ws.write("a.py", "...")."""

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dojo-run-"))
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def write(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
        return p


def py(path: Path) -> Program:
    return build(path)


SUM = """\
    import sys
    data = sys.stdin.read().split()
    print(sum(map(int, data[1:])))
"""
GEN = """\
    from dojo.gen import *
    seed_from_argv()
    n = rint(1, 6)
    out(n, rarray(n, -5, 5))
"""


class CompareTest(unittest.TestCase):
    def test_tokens_ignore_whitespace(self):
        self.assertEqual(compare("1 2\n3\n", "1\n2 3"), (True, ""))
        self.assertEqual(compare("", ""), (True, ""))

    def test_first_difference(self):
        ok, msg = compare("1 2\n4 5\n", "1 2\n3 5\n")
        self.assertFalse(ok)
        self.assertEqual(msg, "line 2, token 3: expected 3, got 4")

    def test_short_and_long_output(self):
        self.assertIn("output ends early: 1 of 2 tokens", compare("1", "1 2")[1])
        self.assertIn("extra output: 3", compare("1 2 3", "1 2")[1])
        self.assertIn("no output", compare("\n", "5")[1])

    def test_case_hint(self):
        ok, msg = compare("yes", "YES")
        self.assertFalse(ok)
        self.assertIn("letter case", msg)

    def test_exact(self):
        self.assertTrue(compare("a b  \nc\n\n", "a b\nc", mode="exact")[0])
        ok, msg = compare("a  b\n", "a b\n", mode="exact")
        self.assertFalse(ok)
        self.assertIn("line 1", msg)
        self.assertIn("ends early", compare("a\n", "a\nb\n", mode="exact")[1])

    def test_float(self):
        self.assertTrue(compare("0.3333334", "0.333333333", mode="float", eps=1e-6)[0])
        self.assertTrue(compare("1000000.5", "1000000.0", mode="float", eps=1e-6)[0])   # relative
        ok, msg = compare("0.34", "0.333333", mode="float", eps=1e-6)
        self.assertFalse(ok)
        self.assertIn("off by", msg)
        self.assertFalse(compare("0.3333334", "0.333333333")[0])                      # tokens mode is strict
        self.assertFalse(compare("abc", "1.0", mode="float")[0])

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            compare("1", "1", mode="fuzzy")


class GenTest(unittest.TestCase):
    def setUp(self):
        gen.rng.seed(42)

    def test_same_seed_same_test(self):
        with Workspace() as ws, TempHome():
            g = py(ws.write("gen.py", GEN))
            a = judge.run(g, "", args=["7"]).stdout
            b = judge.run(g, "", args=["7"]).stdout
            c = judge.run(g, "", args=["8"]).stdout
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        n, *rest = a.split("\n")
        self.assertEqual(len(rest[0].split()), int(n))

    def test_tree_edges_form_a_tree(self):
        for n in (1, 2, 5, 30):
            edges = gen.tree_edges(n)
            self.assertEqual(len(edges), n - 1)
            parent = list(range(n + 1))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x
            for a, b in edges:
                self.assertTrue(1 <= a <= n and 1 <= b <= n)
                ra, rb = find(a), find(b)
                self.assertNotEqual(ra, rb)          # no cycle
                parent[ra] = rb

    def test_graph_edges_simple_and_connected(self):
        for n, m in ((5, 4), (5, 10), (8, 12), (6, 15)):
            edges = gen.graph_edges(n, m, connected=True)
            self.assertEqual(len(edges), m)
            self.assertEqual(len({frozenset(e) for e in edges}), m)
            self.assertTrue(all(a != b for a, b in edges))
            seen, todo = {1}, [1]
            adj = {v: [] for v in range(1, n + 1)}
            for a, b in edges:
                adj[a].append(b)
                adj[b].append(a)
            while todo:
                for w in adj[todo.pop()]:
                    if w not in seen:
                        seen.add(w)
                        todo.append(w)
            self.assertEqual(len(seen), n)
        with self.assertRaises(ValueError):
            gen.graph_edges(4, 7)
        with self.assertRaises(ValueError):
            gen.graph_edges(5, 3, connected=True)

    def test_small_helpers(self):
        self.assertEqual(sorted(gen.perm(6)), [1, 2, 3, 4, 5, 6])
        d = gen.distinct(5, 1, 5)
        self.assertEqual(sorted(d), [1, 2, 3, 4, 5])
        self.assertEqual(len(set(gen.distinct(10, 1, 10**18))), 10)
        with self.assertRaises(ValueError):
            gen.distinct(4, 1, 3)
        self.assertTrue(set(gen.rstring(20, "xy")) <= {"x", "y"})
        self.assertTrue(all(-3 <= v <= 3 for v in gen.rarray(50, -3, 3)))

    def test_out(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            gen.out(3, [1, 2, 3], [(1, 2), (2, 3)], "x y")
        self.assertEqual(buf.getvalue(), "3\n1 2 3\n1 2\n2 3\nx y\n")


class MainClassTest(unittest.TestCase):
    def test_non_public_main_after_helpers(self):
        src = """
            import java.util.*;
            // public class Fake { public static void main(String[] a) {} }
            class Helper { String s = "class X { static void main("; }
            class Main {
                static class Inner { public static void main(String[] a) {} }
                public static void main(String[] args) {}
            }
        """
        self.assertEqual(find_main_class(src), "Main")

    def test_public_preferred_and_none(self):
        self.assertEqual(find_main_class("class B { static public void main(String... a){} }\n"
                                         "public class A { public static void main(String[] a){} }"), "A")
        self.assertIsNone(find_main_class("class Q { int x; void main() {} }"))


def write_prob(ws: Workspace, src: Path, src_path: str, tests, tag="0" * 32, tl=1500) -> Path:
    doc = {"name": "A. Test", "url": "https://codeforces.com/contest/1/problem/A", "timeLimit": tl,
           "memoryLimit": 256, "srcPath": src_path,
           "tests": [{"id": i, "input": a, "output": b} for i, (a, b) in enumerate(tests)]}
    return ws.write(f".cph/.{src.name}_{tag}.prob", json.dumps(doc))


class CphTest(unittest.TestCase):
    def test_matches_src_path(self):
        with Workspace() as ws:
            src = ws.write("A_Test.cpp", "")
            write_prob(ws, src, "/elsewhere/A_Test.cpp", [("9\n", "9\n")], tag="1" * 32)
            write_prob(ws, src, str(src), [("1 2\n", "3\n"), ("5 5\n", "10\n")], tag="2" * 32)
            self.assertEqual(cph.cph_tests(src), [("1 2\n", "3\n"), ("5 5\n", "10\n")])
            self.assertEqual(cph.cph_time_limit(cph.cph_problem(src)), 1.5)

    def test_moved_folder_falls_back_to_file_name(self):
        with Workspace() as ws:
            src = ws.write("[weird] name.cpp", "")
            write_prob(ws, src, "C:\\Users\\a\\cp\\[weird] name.cpp", [("1\n", "1\n")])
            self.assertEqual(cph.cph_tests(src), [("1\n", "1\n")])

    def test_nothing(self):
        with Workspace() as ws:
            src = ws.write("A.cpp", "")
            self.assertIsNone(cph.cph_tests(src))
            ws.write(".cph/.B.cpp_x.prob", "{}")
            ws.write(".cph/.A.cpp_y.prob", "not json")
            self.assertIsNone(cph.cph_tests(src))
            self.assertIsNone(cph.cph_time_limit(None))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.home = TempHome()
        self.home.__enter__()
        self.ws = Workspace().__enter__()

    def tearDown(self):
        self.ws.__exit__()
        self.home.__exit__()

    def test_run_and_judge(self):
        p = py(self.ws.write("sum.py", SUM))
        res = judge.run(p, "3\n1 2 3\n")
        self.assertEqual((res.stdout, res.code, res.timed_out, res.signal), ("6\n", 0, False, None))
        self.assertEqual(judge.judge(res, "6"), ("AC", ""))
        self.assertEqual(judge.judge(res, "7")[0], "WA")
        self.assertEqual(judge.judge(res, None), ("RAN", ""))

    def test_timeout_kills_the_process_group(self):
        p = py(self.ws.write("loop.py", """\
            import subprocess, sys
            subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            while True: pass
        """))
        t0 = time.monotonic()
        res = judge.run(p, "", tl=0.5)
        self.assertTrue(res.timed_out)
        self.assertLess(time.monotonic() - t0, 4)
        self.assertEqual(judge.judge(res, "1")[0], "TLE")

    def test_child_holding_stdout_does_not_hang(self):
        p = py(self.ws.write("bg.py", """\
            import subprocess, sys
            subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            print(1)
        """))
        t0 = time.monotonic()
        res = judge.run(p, "", tl=5)
        self.assertEqual(res.stdout, "1\n")
        self.assertLess(time.monotonic() - t0, 4)

    def test_runtime_errors(self):
        res = judge.run(py(self.ws.write("exit.py", "import sys; sys.exit(3)")), "")
        self.assertEqual(judge.judge(res, "")[0], "RE")
        self.assertIn("exit code 3", res.describe())
        res = judge.run(py(self.ws.write("segv.py", "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)")), "")
        self.assertEqual(res.signal, "SIGSEGV")
        self.assertIn("out of range", judge.judge(res, "")[1])

    def test_output_limit(self):
        p = py(self.ws.write("spam.py", "while True: print('x' * 100)"))
        with mock.patch.object(judge, "OUTPUT_LIMIT", 10_000):
            res = judge.run(p, "", tl=5)
        self.assertTrue(res.output_limit)
        self.assertLessEqual(len(res.stdout), 10_000)
        self.assertEqual(judge.judge(res, "x")[0], "RE")

    def test_program_that_ignores_stdin(self):
        p = py(self.ws.write("hi.py", "print('hi')"))
        res = judge.run(p, "1 " * 300_000)
        self.assertEqual(res.stdout, "hi\n")

    def test_checker(self):
        checker = py(self.ws.write("check.py", """\
            import sys
            inp, out, ans = (open(f).read().split() for f in sys.argv[1:4])
            ok = sorted(out) == sorted(ans)
            print("ok" if ok else "different multiset")
            sys.exit(0 if ok else 1)
        """))
        res = judge.run(py(self.ws.write("cat.py", "print(input())")), "3 1 2\n")
        self.assertEqual(judge.judge(res, "1 2 3", checker=checker, stdin="3 1 2\n"), ("AC", ""))
        verdict, msg = judge.judge(res, "1 2 4", checker=checker, stdin="3 1 2\n")
        self.assertEqual(verdict, "WA")
        self.assertIn("different multiset", msg)

    def test_build_errors(self):
        with self.assertRaises(DojoError) as e:
            build(self.ws.write("bad.py", "def f(:\n"))
        self.assertIn("bad.py, line 1", str(e.exception))
        with self.assertRaises(DojoError):
            build(self.ws.write("x.rs", "fn main() {}"))
        with self.assertRaises(DojoError):
            build(self.ws.dir / "missing.cpp")

    @unittest.skipUnless(HAVE_GXX, "g++ not installed")
    def test_cpp_build_cache_and_errors(self):
        src = self.ws.write("a.cpp", """\
            #include <cstdio>
            int main() { long long a, b; std::scanf("%lld %lld", &a, &b);
            #ifdef LOCAL
              std::fprintf(stderr, "local\\n");
            #endif
              int unused; std::printf("%lld\\n", a + b); }
        """)
        p = build(src)
        self.assertFalse(p.cached)
        self.assertIn("unused", p.warnings)
        res = judge.run(p, "2 40")
        self.assertEqual((res.stdout, res.stderr), ("42\n", "local\n"))
        again = build(src)
        self.assertTrue(again.cached)
        self.assertEqual(again.exe, p.exe)
        self.assertIn("unused", again.warnings)
        bad = self.ws.write("bad.cpp", "int main() { return x; }")
        with self.assertRaises(DojoError) as e:
            build(bad)
        self.assertIn("compile error in bad.cpp", str(e.exception))
        self.assertIn("bad.cpp:1", str(e.exception))
        self.assertNotIn(str(self.ws.dir), str(e.exception))

    @unittest.skipUnless(HAVE_GXX, "g++ not installed")
    def test_cpp_local_header_change_rebuilds(self):
        self.ws.write("v.h", "#define V 1\n")
        src = self.ws.write("h.cpp", '#include <cstdio>\n#include "v.h"\nint main() { std::printf("%d\\n", V); }\n')
        self.assertEqual(judge.run(build(src), "").stdout, "1\n")
        self.ws.write("v.h", "#define V 2\n")
        self.assertEqual(judge.run(build(src), "").stdout, "2\n")

    @unittest.skipUnless(HAVE_JAVA, "javac/java not installed")
    def test_java_non_public_main_in_any_file_name(self):
        src = self.ws.write("A_Koshary.java", """\
            import java.util.*;
            class Helper { static long twice(long x) { return 2 * x; } }
            class Main {
                public static void main(String[] args) {
                    Scanner sc = new Scanner(System.in);
                    System.out.println(Helper.twice(sc.nextLong()));
                }
            }
        """)
        p = build(src)
        self.assertEqual(p.main_class, "Main")
        self.assertEqual(judge.run(p, "21\n", tl=10).stdout.strip(), "42")
        self.assertTrue(build(src).cached)


class StressTest(unittest.TestCase):
    def setUp(self):
        self.home = TempHome()
        self.home.__enter__()
        self.ws = Workspace().__enter__()
        self.gen = py(self.ws.write("gen.py", GEN))
        self.brute = py(self.ws.write("brute.py", SUM))

    def tearDown(self):
        self.ws.__exit__()
        self.home.__exit__()

    def _stress(self, sol: Program, n: int = 15, **kw):
        kw.setdefault("tl", 5.0)
        return stress(sol, self.brute, kw.pop("gen", self.gen), n=n, mode="tokens", eps=1e-6, **kw)

    def test_correct_solution_passes(self):
        sol = py(self.ws.write("sol.py", """\
            n, *a = map(int, open(0).read().split())
            s = 0
            for x in a: s += x
            print(s)
        """))
        seen = []
        res = self._stress(sol, n=12, on_progress=lambda d, n: seen.append(d))
        self.assertTrue(res.ok)
        self.assertEqual(res.iterations, 12)
        self.assertEqual(seen, list(range(1, 13)))
        self.assertGreater(res.distinct, 1)

    def test_finds_the_bug(self):
        sol = py(self.ws.write("sol.py", """\
            n, *a = map(int, open(0).read().split())
            print(sum(x for x in a if x > 0))      # forgets negatives
        """))
        res = self._stress(sol, n=50, seed0=10)
        self.assertFalse(res.ok)
        self.assertEqual(res.verdict, "WA")
        self.assertEqual(res.seed, 10 + res.iterations - 1)
        self.assertIn("expected", res.reason)
        self.assertNotEqual(res.expected, res.got)
        # The saved seed reproduces the same input.
        again = judge.run(self.gen, "", args=[str(res.seed)]).stdout
        self.assertEqual(again, res.failing_input)

    def test_crash_and_brute_failure(self):
        crash = py(self.ws.write("crash.py", "raise SystemExit(1)"))
        res = self._stress(crash, n=3)
        self.assertEqual((res.ok, res.verdict, res.iterations), (False, "RE", 1))
        broken = py(self.ws.write("broken.py", "import sys; sys.exit(2)"))
        res = stress(crash, broken, self.gen, n=3, tl=2, mode="tokens", eps=1e-6)
        self.assertEqual(res.verdict, "BRUTE")
        self.assertIn("brute force", res.reason)

    def test_generator_failure_is_a_dojo_error(self):
        bad = py(self.ws.write("badgen.py", "import sys; print('oops', file=sys.stderr); sys.exit(1)"))
        with self.assertRaises(DojoError) as e:
            self._stress(self.brute, gen=bad)
        self.assertIn("seed 1", str(e.exception))
        self.assertIn("oops", str(e.exception))

    def test_generator_ignoring_seed(self):
        fixed = py(self.ws.write("fixed.py", "print(2); print(1, 2)"))
        res = self._stress(self.brute, n=4, gen=fixed)
        self.assertTrue(res.ok)
        self.assertEqual(res.distinct, 1)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace().__enter__()

    def tearDown(self):
        self.ws.__exit__()

    def test_test_with_input_files(self):
        sol = self.ws.write("sol.py", SUM)
        self.ws.write("t/1.in", "2\n1 2\n")
        self.ws.write("t/1.ans", "3\n")
        self.ws.write("t/2.in", "1\n5\n")
        self.ws.write("t/2.out", "5\n")
        code, out, err = run_cli(["test", str(sol), str(self.ws.dir / "t")])
        self.assertEqual(code, 0, out + err)
        self.assertIn("AC", out)
        self.assertIn("2/2 passed", out)
        self.ws.write("t/2.out", "6\n")
        code, out, _ = run_cli(["test", str(sol), str(self.ws.dir / "t" / "2.in")])
        self.assertEqual(code, 1)
        self.assertIn("WA", out)
        self.assertIn("expected 6, got 5", out)

    def test_test_prefers_ans_over_out(self):
        sol = self.ws.write("sol.py", SUM)
        self.ws.write("stress/fail.in", "1\n5\n")
        self.ws.write("stress/fail.out", "5\n")          # yours
        self.ws.write("stress/fail.ans", "6\n")          # brute force
        code, out, _ = run_cli(["test", str(sol), str(self.ws.dir / "stress" / "fail.in")])
        self.assertEqual(code, 1)
        self.assertIn("expected 6", out)

    def test_test_uses_cph_samples_and_time_limit(self):
        sol = self.ws.write("A_Sum.py", SUM)
        write_prob(self.ws, sol, str(sol), [("2\n1 2\n", "3\n"), ("1\n4\n", "5\n")], tl=3000)
        code, out, _ = run_cli(["test", str(sol)])
        self.assertEqual(code, 1)
        self.assertIn("2 tests from CPH", out)
        self.assertIn("tl 3 s", out)
        self.assertIn("1 of 2 failed", out)

    def test_test_without_tests(self):
        sol = self.ws.write("sol.py", SUM)
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = True
            code, out, err = run_cli(["test", str(sol)])
        self.assertEqual(code, 1)
        self.assertIn("no tests for sol.py", err)
        code, _, err = run_cli(["test", str(self.ws.dir / "nope.cpp")])
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)

    def test_test_json(self):
        sol = self.ws.write("A_Sum.py", SUM)
        write_prob(self.ws, sol, str(sol), [("2\n1 2\n", "3\n"), ("1\n4\n", "5\n")], tl=3000)
        code, out, _ = run_cli(["test", str(sol), "--json"])
        self.assertEqual(code, 1)
        doc = json.loads(out)
        self.assertEqual((doc["file"], doc["source"], doc["tl"], doc["judged"], doc["failed"]), ("A_Sum.py", "CPH", 3.0, 2, 1))
        self.assertEqual([t["verdict"] for t in doc["tests"]], ["AC", "WA"])
        wa = doc["tests"][1]
        self.assertEqual((wa["label"], wa["input"], wa["expected"], wa["got"]), ("#2", "1\n4\n", "5\n", "4\n"))
        self.assertIn("expected 5, got 4", wa["message"])
        self.ws.write("A_Sum.py", "print(")
        code, out, _ = run_cli(["test", str(sol), "--json"])
        doc = json.loads(out)
        self.assertEqual((code, doc["stage"], doc["tests"]), (1, "build", []))
        self.assertIn("syntax error in A_Sum.py", doc["error"])

    def test_stress_json(self):
        sol = self.ws.write("sol.py", """\
            n, *a = map(int, open(0).read().split())
            print(max(0, sum(a)))
        """)
        self.ws.write("brute.py", SUM)
        self.ws.write("gen.py", GEN)
        code, out, err = run_cli(["stress", str(sol), "-n", "60", "--json"])
        self.assertEqual(code, 1, out + err)
        doc = json.loads(out)
        self.assertFalse(doc["ok"])
        self.assertEqual((doc["verdict"], doc["brute"], doc["gen"], doc["n"]), ("WA", "brute.py", "gen.py", 60))
        self.assertEqual(doc["got"].strip(), "0")
        self.assertLess(int(doc["expected"]), 0)
        self.assertEqual(Path(doc["saved"]).read_text(), doc["input"])
        self.ws.write("sol.py", SUM)
        code, out, _ = run_cli(["stress", str(sol), "-n", "8", "--json"])
        doc = json.loads(out)
        self.assertEqual((code, doc["ok"], doc["iterations"], doc["saved"]), (0, True, 8, None))

    def test_stress_init_then_run(self):
        sol = self.ws.write("sol.py", SUM)
        code, out, _ = run_cli(["stress", str(sol), "--init"])
        self.assertEqual(code, 0)
        self.assertTrue((self.ws.dir / "brute.cpp").read_text().startswith("// brute force: simplest correct solution"))
        self.assertIn("#define fast ios::sync_with_stdio(false); cin.tie(NULL);", (self.ws.dir / "brute.cpp").read_text())
        self.assertIn("from dojo.gen import *", (self.ws.dir / "gen.py").read_text())
        (self.ws.dir / "gen.py").write_text("print(1)\n")
        code, out, _ = run_cli(["stress", str(sol), "--init"])
        self.assertIn("kept", out)
        self.assertEqual((self.ws.dir / "gen.py").read_text(), "print(1)\n")

    def test_stress_reports_and_saves_failure(self):
        sol = self.ws.write("sol.py", """\
            n, *a = map(int, open(0).read().split())
            print(max(0, sum(a)))
        """)
        self.ws.write("sol_brute.py", SUM)
        self.ws.write("brute.cpp", "this file must lose to sol_brute.py")
        self.ws.write("gen.py", GEN)
        code, out, err = run_cli(["stress", str(sol), "-n", "60"])
        self.assertEqual(code, 1, out + err)
        self.assertIn("Wrong answer on test", out)
        self.assertIn("vs sol_brute.py", out)
        fail_in = self.ws.dir / "stress" / "fail.in"
        self.assertTrue(fail_in.is_file())
        self.assertEqual((self.ws.dir / "stress" / "fail.out").read_text().strip(), "0")
        self.assertLess(int((self.ws.dir / "stress" / "fail.ans").read_text()), 0)
        self.assertIn("dojo test", out)
        self.assertIn("fail.in", out)

    def test_stress_passes_and_missing_files(self):
        sol = self.ws.write("sol.py", SUM)
        code, _, err = run_cli(["stress", str(sol)])
        self.assertEqual(code, 1)
        self.assertIn("no brute force", err)
        self.ws.write("brute.py", SUM)
        code, _, err = run_cli(["stress", str(sol)])
        self.assertIn("no generator", err)
        self.ws.write("gen.py", GEN)
        code, out, err = run_cli(["stress", str(sol), "-n", "8"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("8/8 random tests passed", out)


if __name__ == "__main__":
    unittest.main()
