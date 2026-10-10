"""dojo java — C++ -> Java cheat sheet for competitive programming.

Every snippet here is compiled (and the ones with `expect` are run) by tests/test_scaffold.py,
so the sheet can't drift into code that doesn't build.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field

from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.term import Term

IMPORTS = "import java.io.*;\nimport java.util.*;\n"


@dataclass
class Snippet:
    code: str
    kind: str = "stmts"             # "stmts": the body of main; "members": fields, methods, types, main
    stdin: str = ""
    expect: str | None = None       # exact stdout; tests run the snippet and compare

    def source(self, cls: str) -> str:
        """A compilable file declaring class `cls`."""
        code = textwrap.dedent(self.code).strip("\n")
        if self.kind == "stmts":
            body = textwrap.indent(code, " " * 8)
            return (f"{IMPORTS}\nclass {cls} {{\n    public static void main(String[] args) throws Exception {{\n"
                    f"{body}\n    }}\n}}\n")
        return f"{IMPORTS}\nclass {cls} {{\n{textwrap.indent(code, ' ' * 4)}\n}}\n"


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]


@dataclass
class Section:
    key: str
    title: str
    aliases: tuple[str, ...]
    blocks: list[str | Snippet | Table] = field(default_factory=list)

    @property
    def snippets(self) -> list[Snippet]:
        return [b for b in self.blocks if isinstance(b, Snippet)]


SECTIONS: list[Section] = [
    Section("io", "I/O", ("input", "output", "scanner", "fast"), [
        "- Scanner is several times slower than cin: on 2·10^5 numbers it can TLE. Read with "
        "BufferedReader + StringTokenizer.",
        "- System.out.println once per line is slow too. Print into a PrintWriter and flush once at the "
        "end. Forget out.flush() and nothing is printed: WA on test 1.",
        "- Whole line (getline): br.readLine(). It returns null at end of input.",
        "- dojo new <id> --java writes a file with all of this ready.",
        Snippet("""
            static BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
            static StringTokenizer st;

            static String next() throws IOException {
                while (st == null || !st.hasMoreTokens()) st = new StringTokenizer(br.readLine());
                return st.nextToken();
            }
            static int nextInt() throws IOException { return Integer.parseInt(next()); }    // cin >> n
            static long nextLong() throws IOException { return Long.parseLong(next()); }

            public static void main(String[] args) throws IOException {
                PrintWriter out = new PrintWriter(new BufferedWriter(new OutputStreamWriter(System.out)));
                int n = nextInt();
                long sum = 0;
                for (int i = 0; i < n; i++) sum += nextLong();
                out.println(sum);                       // cout << sum << '\\n'
                out.printf("%.3f%n", sum / 4.0);        // printf works like C's
                out.flush();                            // forget this and nothing is printed
            }
        """, kind="members", stdin="3\n1 2\n3\n", expect="6\n1.500\n"),
    ]),
    Section("types", "Types & overflow", ("int", "long", "overflow", "division", "mod"), [
        "- int is 32-bit, long is 64-bit. There is no long long and no unsigned. Use long for sums, "
        "products and anything near 10^9.",
        "- int * int overflows before it is widened: long x = a * b is wrong; write (long) a * b.",
        "- 1 << 40 is an int shift (the distance is taken mod 32): it gives 256. Write 1L << 40.",
        "- / and % truncate toward zero, as in C++: -7 / 2 == -3, -7 % 2 == -1. For a non-negative "
        "remainder use Math.floorMod(-7, 2) == 1.",
        "- boolean is not a number: if (n) does not compile; write if (n != 0). char is a number: "
        "'a' + 1 is the int 98, (char) ('a' + 1) is 'b'.",
        "- Math.addExact / Math.multiplyExact throw on overflow: a quick way to find where it happens.",
        Snippet("""
            int a = 100000, b = 100000;
            long wrong = a * b;              // int * int overflowed first
            long right = (long) a * b;
            System.out.println(wrong + " " + right);                              // 1410065408 10000000000
            System.out.println((1 << 40) + " " + (1L << 40));                     // 256 1099511627776
            System.out.println(-7 / 2 + " " + -7 % 2 + " " + Math.floorMod(-7, 2)); // -3 -1 1
            final long MOD = 1_000_000_007L;
            System.out.println((1L << 40) % MOD + " " + (char) ('a' + 1) + " " + ('a' + 1));
            System.out.println(Integer.MAX_VALUE + " " + Long.MAX_VALUE);
        """, expect="1410065408 10000000000\n256 1099511627776\n-3 -1 1\n511620083 b 98\n"
                    "2147483647 9223372036854775807\n"),
    ]),
    Section("strings", "Strings", ("string", "stringbuilder", "equals", "char"), [
        "- Strings are immutable. s.charAt(i), not s[i]; s.length() (arrays: a.length, lists: list.size()).",
        "- s += c in a loop copies the whole string every time: O(n²). Build with StringBuilder.",
        "- == compares references, not text. Use a.equals(b), and a.compareTo(b) for order.",
        "- substring(begin, end) takes an end index, not a length like C++ substr(pos, len).",
        Snippet("""
            String s = "hello";
            char c = s.charAt(1);                        // s[1]
            String t = s.substring(1, 3);                // [1, 3) -> "el"
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 3; i++) sb.append(i).append(' ');
            sb.reverse();
            System.out.println(c + " " + t + " [" + sb + "]");          // e el [ 2 1 0]

            String a = new String("yes");                // what reading input gives you: a new object
            System.out.println((a == "yes") + " " + a.equals("yes"));  // false true

            char[] cs = s.toCharArray();
            Arrays.sort(cs);
            System.out.println(new String(cs) + " " + "abc".compareTo("abd"));       // ehllo -1
            System.out.println(Integer.parseInt("42") + " " + Integer.toBinaryString(10)
                               + " " + String.valueOf(7) + Long.parseLong("123456789012"));
        """, expect="e el [ 2 1 0]\nfalse true\nehllo -1\n42 1010 7123456789012\n"),
    ]),
    Section("arrays", "Arrays & sorting", ("array", "sort", "sorting", "comparator", "quicksort"), [
        "- new int[n] is zero-filled; 2D: new int[n][m]. memset(dp, -1) is Arrays.fill on each row.",
        "- Arrays.sort(int[]) (also long[], double[]) is a quicksort. Codeforces hackers add "
        "anti-quicksort tests that make it O(n²), so it passes in the round and gets TLE after the hacks. "
        "Shuffle first, or sort an Integer[] / Long[] / ArrayList: object sorts are merge sorts, "
        "always O(n log n).",
        "- Primitive arrays take no comparator. For a custom order sort Integer[] or int[][] with a "
        "lambda, comparing with Integer.compare(x, y), never x - y (it overflows).",
        "- Arrays.binarySearch returns -(insertion point) - 1 when the value is missing; for "
        "lower_bound write the loop (or use TreeSet.ceiling).",
        Snippet("""
            static void shuffleSort(int[] a) {
                Random r = new Random();
                for (int i = a.length - 1; i > 0; i--) {
                    int j = r.nextInt(i + 1);
                    int t = a[i]; a[i] = a[j]; a[j] = t;
                }
                Arrays.sort(a);
            }

            static int lowerBound(int[] a, int x) {      // first index with a[i] >= x
                int lo = 0, hi = a.length;
                while (lo < hi) {
                    int mid = (lo + hi) >>> 1;
                    if (a[mid] < x) lo = mid + 1; else hi = mid;
                }
                return lo;
            }

            public static void main(String[] args) {
                int[] a = {5, 3, 9, 1};
                shuffleSort(a);
                System.out.println(Arrays.toString(a) + " " + lowerBound(a, 4));   // [1, 3, 5, 9] 2

                Integer[] b = {5, 3, 9, 1};
                Arrays.sort(b, Collections.reverseOrder());                       // descending
                System.out.println(Arrays.toString(b));                           // [9, 5, 3, 1]

                int[][] seg = {{3, 9}, {1, 4}, {3, 2}};
                Arrays.sort(seg, (x, y) -> x[0] != y[0] ? Integer.compare(x[0], y[0])
                                                        : Integer.compare(x[1], y[1]));
                System.out.println(Arrays.deepToString(seg));                     // [[1, 4], [3, 2], [3, 9]]

                long[][] dp = new long[3][4];
                for (long[] row : dp) Arrays.fill(row, -1);                       // memset(dp, -1, ...)
                List<Integer> list = new ArrayList<>(List.of(3, 1, 2));
                Collections.sort(list);                                           // sort(all(v))
                System.out.println(dp[2][3] + " " + list);                        // -1 [1, 2, 3]
            }
        """, kind="members", expect="[1, 3, 5, 9] 2\n[9, 5, 3, 1]\n[[1, 4], [3, 2], [3, 9]]\n-1 [1, 2, 3]\n"),
    ]),
    Section("collections", "Collections (STL → java.util)", ("stl", "map", "set", "pq", "priority", "queue",
                                                              "stack", "pair", "vector"), [
        Table(["C++", "Java", "notes"], [
            ["vector<int>", "ArrayList<Integer>", "add, get(i), set(i, x), size()"],
            ["map<K, V>", "TreeMap<K, V>", "get returns null if absent; firstKey, floorKey, ceilingKey"],
            ["unordered_map<K, V>", "HashMap<K, V>", "getOrDefault(k, 0), merge(k, 1, Integer::sum)"],
            ["set<int>", "TreeSet<Integer>", "first, last, floor, ceiling, lower, higher"],
            ["multiset<int>", "TreeMap<Integer, Integer>", "value = count; remove the key at 0"],
            ["unordered_set<int>", "HashSet<Integer>", "add, contains, remove"],
            ["priority_queue<int>", "PriorityQueue<Integer>", "MIN-heap by default (C++ is max)"],
            ["", "", "max-heap: new PriorityQueue<>(Collections.reverseOrder())"],
            ["queue<int>", "ArrayDeque<Integer>", "offer, poll, peek"],
            ["stack<int>", "ArrayDeque<Integer>", "push, pop, peek (not the old Stack class)"],
            ["deque<int>", "ArrayDeque<Integer>", "offerFirst/offerLast, pollFirst/pollLast"],
            ["pair<int, int>", "record P(int a, int b)", "or long[]{a, b}; records get equals/hashCode"],
        ]),
        "- Collections hold objects (Integer, Long), not int: see `dojo java boxing` before comparing them.",
        "- map.get(k) on a missing key returns null; int c = map.get(k) then throws NullPointerException.",
        Snippet("""
            record P(int a, int b) {}

            public static void main(String[] args) {
                PriorityQueue<Integer> minHeap = new PriorityQueue<>();
                PriorityQueue<Integer> maxHeap = new PriorityQueue<>(Collections.reverseOrder());
                for (int x : new int[]{4, 1, 7}) { minHeap.add(x); maxHeap.add(x); }
                System.out.println(minHeap.poll() + " " + maxHeap.poll());          // 1 7

                Map<String, Integer> cnt = new HashMap<>();
                for (String w : "a b a c a".split(" ")) cnt.merge(w, 1, Integer::sum);   // cnt[w]++
                System.out.println(cnt.get("a") + " " + cnt.getOrDefault("z", 0));  // 3 0

                TreeSet<Integer> set = new TreeSet<>(List.of(10, 20, 30));
                System.out.println(set.ceiling(15) + " " + set.floor(5));          // 20 null (none)

                TreeMap<Integer, Integer> multiset = new TreeMap<>();
                multiset.merge(5, 1, Integer::sum);
                multiset.merge(5, 1, Integer::sum);
                if (multiset.merge(5, -1, Integer::sum) == 0) multiset.remove(5);   // erase one copy
                System.out.println(multiset);                                       // {5=1}

                ArrayDeque<Integer> stack = new ArrayDeque<>();
                stack.push(1);
                stack.push(2);
                ArrayDeque<P> queue = new ArrayDeque<>();
                queue.offer(new P(1, 2));
                System.out.println(stack.pop() + " " + queue.poll().a());           // 2 1
            }
        """, kind="members", expect="1 7\n3 0\n20 null\n{5=1}\n2 1\n"),
    ]),
    Section("boxing", "Integer caching: == on boxed numbers", ("integer", "cache", "==", "boxed"), [
        "- == on two Integer (or Long) objects compares references. Java caches -128…127, so == "
        "works on the small numbers in your samples and fails on big ones in the judge's tests.",
        "- Compare with a.equals(b), or unbox first: int x = list.get(i).",
        "- list.remove(i) removes index i; list.remove(Integer.valueOf(x)) removes the value x.",
        Snippet("""
            Integer a = 127, b = 127, c = 128, d = 128;
            System.out.println((a == b) + " " + (c == d) + " " + c.equals(d));   // true false true
            List<Integer> list = new ArrayList<>(List.of(5, 1000, 1000));
            System.out.println(list.get(1) == list.get(2));                      // false: two objects
            int x = list.get(1);
            System.out.println(x == list.get(2));                                // true: int == Integer unboxes
            list.remove(Integer.valueOf(5));                                     // the value 5
            list.remove(0);                                                      // index 0
            System.out.println(list);                                            // [1000]
        """, expect="true false true\nfalse\ntrue\n[1000]\n"),
    ]),
    Section("recursion", "Recursion depth", ("stack", "dfs", "stackoverflow", "thread"), [
        "- Java's default stack is small: a DFS 10^5 deep throws StackOverflowError (RE) where the "
        "same C++ passes.",
        "- Run the solution in a thread with a bigger stack. 1 << 26 (64 MB) handles depth 2·10^5 of "
        "a small function; for 10^6 levels, write the DFS with an explicit ArrayDeque stack.",
        Snippet("""
            static int depth(int n) { return n == 0 ? 0 : 1 + depth(n - 1); }

            public static void main(String[] args) throws InterruptedException {
                Thread t = new Thread(null, () -> {
                    System.out.println(depth(200_000));   // overflows the default stack
                }, "solve", 1 << 26);
                t.start();
                t.join();
            }
        """, kind="members", expect="200000\n"),
    ]),
    Section("errors", "Common CE / RE / TLE on Codeforces", ("ce", "re", "tle", "wa", "mistakes", "pitfalls"), [
        "Compilation error",
        "- A package line your IDE added: delete it, the judge runs the class without a package.",
        "- Missing imports: start every file with import java.util.*; and import java.io.*;",
        "- Checked exceptions: readLine() throws IOException, so main and every helper that reads "
        "need throws IOException.",
        "- The wrong language in the dropdown: pick Java 21.",
        "Runtime error",
        "- NullPointerException: unboxing a missing map value (int c = map.get(k)). Use getOrDefault.",
        "- NumberFormatException: Integer.parseInt on a whole line like \"3 4\", or on a number that "
        "needs a long.",
        "- ArrayIndexOutOfBoundsException, StackOverflowError (dojo java recursion), and "
        "NoSuchElementException from Scanner reading past the input.",
        "Time limit / wrong answer",
        "- TLE: Scanner and println in big loops, String += in a loop, Arrays.sort(int[]) after a hack, "
        "ArrayList<Integer> or HashMap in a hot loop where an int[] would do.",
        "- WA: no out.flush() (empty output), int overflow, == on String or Integer.",
        Snippet("""
            Map<Integer, Integer> seen = new HashMap<>();
            // int c = seen.get(42);                 // NullPointerException: get returned null
            int c = seen.getOrDefault(42, 0);
            long n = Long.parseLong("10000000000");  // Integer.parseInt here: NumberFormatException
            String[] parts = "3 4".trim().split("\\\\s+");
            System.out.println(c + " " + n + " " + (Integer.parseInt(parts[0]) + Integer.parseInt(parts[1])));
        """, expect="0 10000000000 7\n"),
    ]),
]


def find_section(topic: str) -> Section:
    t = topic.strip().lower()
    for s in SECTIONS:
        if t == s.key or t in s.aliases:
            return s
    matches = [s for s in SECTIONS if s.key.startswith(t) or any(a.startswith(t) for a in s.aliases)]
    if len(matches) == 1:
        return matches[0]
    raise DojoError(f"no Java topic {topic!r} — try one of: {', '.join(s.key for s in SECTIONS)}")


def _code(code: str, term: Term) -> str:
    out = []
    for line in textwrap.dedent(code).strip("\n").splitlines():
        cut = line.find("//")
        if cut >= 0 and line[:cut].count('"') % 2 == 0:
            line = line[:cut] + term.muted(line[cut:])
        out.append("    " + line if line.strip() else "")
    return "\n".join(out)


def render_section(sec: Section, term: Term) -> str:
    width = max(40, min(term.width, 110) - 4)
    parts = [term.section(sec.title)]
    prev = None
    for b in sec.blocks:
        kind = type(b)
        if prev is not None and (kind is not str or prev is not str):
            parts.append("")                    # code and tables get air around them
        if isinstance(b, Snippet):
            parts.append(_code(b.code, term))
        elif isinstance(b, Table):
            parts.append(term.table(b.rows, header=b.header))
        elif b.startswith("- "):
            parts.append(textwrap.fill(b[2:], width, initial_indent="  - ", subsequent_indent="    "))
        else:
            parts.append("  " + term.s(b, "bold"))
        prev = kind
    return "\n".join(parts)


def register(sub, common):
    p = add_command(sub, common, "java", "C++ -> Java cheat sheet for competitive programming",
                    description="C++ -> Java for competitive programming (CIS 201 is taught in Java).\n"
                                "Topics: " + ", ".join(f"{s.key}" for s in SECTIONS) + ".\n"
                                "Every snippet compiles with JDK 21; dojo new <id> --java gives you a ready file.")
    p.add_argument("topic", nargs="?", help="one section: " + ", ".join(s.key for s in SECTIONS))
    p.add_argument("--list", action="store_true", help="list the topics")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    term, args = ctx.term, ctx.args
    if args.list:
        term.out(term.table([[term.s(s.key, "bold"), s.title] for s in SECTIONS]))
        return 0
    if args.topic:
        term.out(render_section(find_section(args.topic), term).lstrip("\n"))
        return 0
    term.out(term.title("Java for C++ programmers") + term.muted(" · competitive programming on Codeforces"))
    for s in SECTIONS:
        term.out(render_section(s, term))
    term.out("", term.muted("  one topic: dojo java <" + "|".join(s.key for s in SECTIONS) + ">"),
             term.muted("  a ready file: dojo new <id> --java"))
    return 0
