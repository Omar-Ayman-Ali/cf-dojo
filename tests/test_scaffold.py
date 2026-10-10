import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dojo.commands import java as javasheet
from dojo.commands.new import ProblemRef, file_stem, parse_problem, render_file, words
from dojo.errors import DojoError
from dojo.term import Term
from tests.fixtures import TempHome, make_snapshot, prob, run_cli

# DESIGN.md §1: his template, byte for byte.
HIS_TEMPLATE = """#include <bits/stdc++.h>
using namespace std;

#define fast ios::sync_with_stdio(false); cin.tie(NULL);
#define all(x) x.begin(), x.end()
#define rall(x) x.rbegin(), x.rend()

typedef long long ll;
typedef vector<int> vi;

int main() {
    fast;

    return 0;
}
"""
TEMPLATES = Path(__file__).resolve().parent.parent / "dojo" / "run" / "templates"
JAVA_ENV = {k: v for k, v in os.environ.items() if k not in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS")}
JAVA_FLAGS = ["-Duser.language=en", "-Duser.country=US"]        # printf's decimal point, as on Codeforces


def snap():
    return make_snapshot(problems=[prob("2227A", 800, name="Koshary"), prob("1850G", 1600, name="The Morning Star"),
                                   prob("2254C1", 1200, name="Marenol (easy version)")])


class ParseProblemTest(unittest.TestCase):
    def test_keys(self):
        for text, want in [("2227A", (2227, "A")), ("2227a", (2227, "A")), ("2227 A", (2227, "A")),
                           (" 2227/b1 ", (2227, "B1")), ("2254C1", (2254, "C1")), ("596491D", (596491, "D"))]:
            r = parse_problem(text)
            self.assertEqual((r.contest_id, r.index), want, text)
            self.assertIsNone(r.url)

    def test_urls(self):
        cases = [
            ("https://codeforces.com/contest/2227/problem/A?locale=en", 2227, "A",
             "https://codeforces.com/contest/2227/problem/A"),
            ("https://codeforces.com/problemset/problem/1850/G", 1850, "G", "https://codeforces.com/contest/1850/problem/G"),
            ("codeforces.com/gym/104114/problem/B", 104114, "B", "https://codeforces.com/gym/104114/problem/B"),
            ("https://m1.codeforces.com/group/abcDEF12/contest/219158/problem/F2#statement", 219158, "F2",
             "https://codeforces.com/group/abcDEF12/contest/219158/problem/F2"),
            ("https://codeforces.com/problemset/gymProblem/104114/C", 104114, "C",
             "https://codeforces.com/gym/104114/problem/C"),
        ]
        for text, cid, idx, url in cases:
            r = parse_problem(text)
            self.assertEqual((r.contest_id, r.index, r.url), (cid, idx, url), text)
        self.assertEqual(parse_problem(cases[3][0]).group, "abcDEF12")

    def test_bad(self):
        for text in ("", "A2227", "hello", "2227", "https://codeforces.com/contest/2227", "2227AB"):
            with self.assertRaises(DojoError, msg=text):
                parse_problem(text)


class FileNameTest(unittest.TestCase):
    def test_like_cph(self):
        # Real names from ~/cppprimer, made by Competitive Programming Helper.
        self.assertEqual(file_stem("A", "Koshary"), "A_Koshary")
        self.assertEqual(file_stem("D", "Vlad and the Best of Five"), "D_Vlad_and_the_Best_of_Five")
        self.assertEqual(file_stem("G1", "Strange Summation"), "G_1_Strange_Summation")
        self.assertEqual(file_stem("I", "Max 2D Box"), "I_Max_2_D_Box")
        self.assertEqual(file_stem("F", "3-D"), "F_3_D")
        self.assertEqual(file_stem("A", "Is It Frequency?"), "A_Is_It_Frequency")
        self.assertEqual(file_stem("C1", "Marenol (easy version)"), "C_1_Marenol_easy_version")

    def test_words(self):
        self.assertEqual(words("XMLParser camelCase"), ["XML", "Parser", "camel", "Case"])
        self.assertEqual(words("Bus to Pénjamo"), ["Bus", "to", "Pénjamo"])
        self.assertEqual(words("!!!"), [])

    def test_header(self):
        ref = ProblemRef(2227, "A")
        text = render_file(ref, "Koshary", "https://codeforces.com/contest/2227/problem/A", java=False)
        self.assertEqual(text, "// 2227A Koshary — https://codeforces.com/contest/2227/problem/A\n" + HIS_TEMPLATE)
        text = render_file(ref, "", "https://x", java=True)
        self.assertTrue(text.startswith("// 2227A — https://x\nimport java.io.*;"))


class NewCommandTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dojo-new-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def new(self, *argv, snapshot=None, home=None):
        return run_cli(["new", *argv, "--dir", self.dir], snap=snapshot or snap(), home=home)

    def test_cpp_file(self):
        code, out, err = self.new("2227A")
        self.assertEqual(code, 0, err)
        path = Path(self.dir) / "A_Koshary.cpp"
        self.assertEqual(out.splitlines()[0], str(path))
        self.assertIn("dojo test A_Koshary.cpp", out)
        self.assertEqual(path.read_text(),
                         "// 2227A Koshary — https://codeforces.com/contest/2227/problem/A\n" + HIS_TEMPLATE)

    def test_split_key_and_creates_dir(self):
        sub = Path(self.dir) / "a" / "b"
        code, out, err = run_cli(["new", "1850", "G", "--dir", str(sub)], snap=snap())
        self.assertEqual(code, 0, err)
        self.assertTrue((sub / "G_The_Morning_Star.cpp").exists())

    def test_never_overwrites_without_force(self):
        self.new("2227A")
        path = Path(self.dir) / "A_Koshary.cpp"
        path.write_text("my work")
        code, _, err = self.new("2227A")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertIn("--force", err)
        self.assertEqual(path.read_text(), "my work")
        code, _, _ = self.new("2227A", "--force")
        self.assertEqual(code, 0)
        self.assertTrue(path.read_text().startswith("// 2227A Koshary"))

    def test_java(self):
        code, out, err = self.new("2227A", "--java")
        self.assertEqual(code, 0, err)
        text = (Path(self.dir) / "A_Koshary.java").read_text()
        self.assertTrue(text.startswith("// 2227A Koshary — https://codeforces.com/contest/2227/problem/A\n"))
        self.assertIn("\nclass Main {", text)
        self.assertNotRegex(text, r"(?m)^\s*public\s+(final\s+)?class")
        self.assertIn("the class is Main", out)

    def test_group_url_with_name_needs_no_data(self):
        url = "https://codeforces.com/group/abcDEF12/contest/219158/problem/B"
        code, out, err = run_cli(["new", url, "--name", "Hello, World!", "--dir", self.dir], snap=None)
        self.assertEqual(code, 0, err)                      # run_cli fails if Codeforces data is loaded
        text = (Path(self.dir) / "B_Hello_World.cpp").read_text()
        self.assertTrue(text.startswith(f"// 219158B Hello, World! — {url}\n"))

    def test_group_problem_url_from_cph_codes(self):
        s = snap()
        s.group_codes = {219158: "abcDEF12"}
        code, _, _ = self.new("219158C", "--name", "Sum", snapshot=s)
        self.assertEqual(code, 0)
        text = (Path(self.dir) / "C_Sum.cpp").read_text()
        self.assertIn("https://codeforces.com/group/abcDEF12/contest/219158/problem/C", text.splitlines()[0])

    def test_unknown_name(self):
        code, out, err = self.new("104114B")
        self.assertEqual(code, 0, err)
        self.assertTrue((Path(self.dir) / "104114B.cpp").exists())
        self.assertIn("--name", out)
        self.assertTrue((Path(self.dir) / "104114B.cpp").read_text().startswith(
            "// 104114B — https://codeforces.com/gym/104114/problem/B\n"))

    def test_offline_without_problemset(self):
        s = make_snapshot()
        s.loaded = set()
        code, _, _ = self.new("2227A", snapshot=s)
        self.assertEqual(code, 0)
        self.assertTrue((Path(self.dir) / "2227A.cpp").exists())

    def test_bad_problem(self):
        code, _, err = self.new("hello")
        self.assertEqual(code, 1)
        self.assertIn("not a problem id", err)

    def test_custom_template_and_editor(self):
        with TempHome() as home:
            tpl = Path(home) / "my.cpp"
            tpl.write_text("// mine\nint main() {}")
            cfg = Path(home) / "config" / "config.toml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(f'[workspace]\ntemplate = "{tpl}"\neditor = "code -r"\n')
            with mock.patch("dojo.commands.new.subprocess.run") as run:
                code, _, err = self.new("2227A", "--open", home=home)
            self.assertEqual(code, 0, err)
            path = Path(self.dir) / "A_Koshary.cpp"
            self.assertEqual(path.read_text(),
                             "// 2227A Koshary — https://codeforces.com/contest/2227/problem/A\n// mine\nint main() {}\n")
            run.assert_called_once_with(["code", "-r", str(path)], check=False)

            cfg.write_text('[workspace]\ntemplate = "/nonexistent/tpl.cpp"\neditor = "no-such-editor-dojo"\n')
            code, _, err = self.new("1850G", home=home)
            self.assertEqual(code, 1)
            self.assertIn("can't read your template", err)
            cfg.write_text('[workspace]\neditor = "no-such-editor-dojo"\n')
            code, _, err = self.new("1850G", "--open", home=home)
            self.assertEqual(code, 1)
            self.assertIn("can't run your editor", err)
            self.assertTrue((Path(self.dir) / "G_The_Morning_Star.cpp").exists())


class TemplateTest(unittest.TestCase):
    def test_cpp_template_is_his(self):
        self.assertEqual((TEMPLATES / "solution.cpp").read_text(), HIS_TEMPLATE)

    @unittest.skipUnless(shutil.which("g++"), "g++ not installed")
    def test_cpp_template_compiles(self):
        r = subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"], input=HIS_TEMPLATE,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "javac/java not installed")
    def test_java_template_compiles_and_passes_a_sample(self):
        text = render_file(ProblemRef(2227, "A"), "Koshary", "https://codeforces.com/contest/2227/problem/A", java=True)
        self.assertIn("// your code", text)
        body = ("int n = in.nextInt(); long[] a = readLongs(n); safeSort(a); long s = 0;\n"
                "        for (long x : a) s += x;\n"
                "        out.println(s + \" \" + a[0] + \" \" + a[n - 1]);\n"
                "        out.println(in.nextLine() + \"|\" + in.nextLine());")
        text = text.replace("// your code", body)
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "A_Koshary.java"                 # file name != class name: must still compile
            src.write_text(text)
            r = subprocess.run(["javac", "-d", d, str(src)], capture_output=True, text=True, timeout=120, env=JAVA_ENV)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run(["java", *JAVA_FLAGS, "-cp", d, "Main"], input="4\n3000000000 -1\n7\n 2\nrest of line\nnext line\n",
                               capture_output=True, text=True, timeout=60, env=JAVA_ENV)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "3000000008 -1 3000000000\nrest of line|next line\n")


class JavaSheetTest(unittest.TestCase):
    def test_sections_from_design(self):
        keys = [s.key for s in javasheet.SECTIONS]
        self.assertEqual(keys, ["io", "types", "strings", "arrays", "collections", "boxing", "recursion", "errors"])
        text = "\n".join(str(b) for s in javasheet.SECTIONS for b in s.blocks)
        for must in ("Math.floorMod", "StringBuilder", "equals", "Arrays.sort(int[])", "TreeMap", "HashMap",
                     "TreeSet", "PriorityQueue", "MIN-heap", "record", "-128…127", "1 << 26", "throws IOException"):
            self.assertIn(must, text)

    def test_command(self):
        code, out, err = run_cli(["java"])
        self.assertEqual(code, 0, err)
        for s in javasheet.SECTIONS:
            self.assertIn(s.title.upper(), out)
        code, out, _ = run_cli(["java", "coll"])
        self.assertEqual(code, 0)
        self.assertIn("PriorityQueue<Integer>", out)
        self.assertNotIn("STRINGS", out)
        code, out, _ = run_cli(["java", "pq"])
        self.assertIn("COLLECTIONS", out)
        code, out, _ = run_cli(["java", "--list"])
        self.assertIn("recursion", out)
        code, _, err = run_cli(["java", "kotlin"])
        self.assertEqual(code, 1)
        self.assertIn("io, types", err)

    def test_narrow_terminal_wraps_prose(self):
        term = Term(color=False, links=False, width=50, stream=io.StringIO())
        lines = javasheet.render_section(javasheet.find_section("types"), term).splitlines()
        bullets = [i for i, line in enumerate(lines) if line.startswith("  - ")]
        self.assertTrue(all(len(lines[i]) <= 50 for i in bullets))
        self.assertTrue(lines[bullets[0] + 1].startswith("    ") and "//" not in lines[bullets[0] + 1])

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "javac/java not installed")
    def test_every_snippet_compiles_and_prints_what_it_claims(self):
        snippets = [(f"S{i:02d}", sn) for i, sn in enumerate(sn for s in javasheet.SECTIONS for sn in s.snippets)]
        self.assertGreaterEqual(len(snippets), 8)
        with tempfile.TemporaryDirectory() as d:
            files = []
            for cls, sn in snippets:
                f = Path(d) / f"{cls}.java"
                f.write_text(sn.source(cls))
                files.append(str(f))
            r = subprocess.run(["javac", "-d", d, *files], capture_output=True, text=True, timeout=180, env=JAVA_ENV)
            self.assertEqual(r.returncode, 0, r.stderr)
            for cls, sn in snippets:
                if sn.expect is None:
                    continue
                r = subprocess.run(["java", *JAVA_FLAGS, "-cp", d, cls], input=sn.stdin, capture_output=True,
                                   text=True, timeout=60, env=JAVA_ENV)
                self.assertEqual(r.returncode, 0, f"{cls}: {r.stderr}")
                self.assertEqual(r.stdout, sn.expect, f"{cls}:\n{sn.code}")


if __name__ == "__main__":
    unittest.main()
