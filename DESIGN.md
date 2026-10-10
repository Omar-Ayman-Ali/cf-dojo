# dojo — design contract

`dojo` is a training CLI and local web app for competitive programming and computer science practice. It has two main pillars:

1. **Codeforces coach**: what to solve today, weak tags, upsolve and retry queues, upcoming contests, a local judge with stress testing, and Java practice for competitive programming.
2. **Course drills**: unlimited generated practice with instant checking and worked solutions for Logic Design (Boolean algebra, Karnaugh maps, two's complement), Discrete Mathematics (truth tables, propositional logic) and Statistical Analysis (descriptive statistics, distributions, z-scores).

This document serves as the architecture specification and contract between modules.

---

## 1. Architecture & Design Principles

- **Focus & Deliberate Practice**: Replaces mindless grinding with targeted training. Plans are structured into warm-up, core (targeting weak tags), stretch, and re-solve components.
- **Local-First & Offline-Ready**: Works without external dependencies or heavy frameworks. Code runs locally with standard library Python 3.11+.
- **Zero Mascots, High Signal**: Calm, dense information architecture without gamified noise.
- **Local Judge & Stress Tester**: Scaffolds problem solutions in C++ and Java, verifies against test cases, and runs brute-force stress tests to catch edge cases.
- **Interactive Drills**: Generates step-by-step worked solutions for fundamental CS concepts (Quine–McCluskey, Petrick's method, Boolean simplification, two's complement arithmetic, probability and statistics).

## 2. Development Guidelines

- **Python >= 3.11, standard library only.** No third-party package dependencies required at runtime.
- `from __future__ import annotations` at the top of every module. Clean type hints on public functions.
- **No network in unit tests.** All tests run against deterministic mock snapshots and fixtures in temporary directories.
- **Local security**: The web server binds strictly to `127.0.0.1` and requires a per-run cryptographic token. Never print or log secrets.
- **User-facing text**: Plain, direct, concise English.
- Errors the user can fix -> `raise DojoError("what's wrong — what to do")`.


## 3. Foundation (already written — read the code, it's short)

| Module | What it gives you |
|---|---|
| `dojo/config.py` | `Config` (handle, target_rating, timezone/`tz`, `week_start_day`, weekly_goal, plan_size, `java_weekdays`, min_contest_id, hide_tags, `workspace_path`, template, editor, `cph_paths`, `schedule: list[ClassSlot(day, start, end, what)]`), `load()`, `DEFAULT_TOML`, `parse_day`. |
| `dojo/paths.py` | `config_dir()`, `cache_dir()`, `data_dir()`, `ensure(path)`. Honour `DOJO_HOME`. |
| `dojo/term.py` | `Term`: `s(text, *styles)`, `rating(r)`, `link(text, url)`, `bar(frac)`, `spark(values)`, `table(rows, header=, align=)`, `kv(pairs)`, `section(title)`, `title()`, `muted()`, `out()`, `note()`, `warn()`. Module: `rank_of`, `next_rank`, `width_of`, `pad`, `truncate`, `strip`, `CHECK`, `CROSS`, `DOT`, `ARROW`. Styles: accent good bad warn info muted violet orange bold dim italic underline '#hex'. |
| `dojo/state.py` | `State`: `get(section, default)` returns a live object; mutate then `touch(section)`; or `set(section, value)`. Saved automatically at exit. Sections: `plans` (today), `resolve` (retry), `drill`. |
| `dojo/timeutil.py` | `local`, `local_date`, `week_start`, `day_start_ts`, `fmt_duration`, `fmt_ago`, `fmt_when` ('Wed 07 Oct 17:35'), `fmt_day`. |
| `dojo/cf/model.py` | `Problem(contest_id, index, name, rating, tags, solved_count, type)` `.key .is_gym`; `Submission(...)` `.key .ok .failed .in_contest .is_gym`; `RatingChange`; `Contest(id, name, type, phase, duration, start)` `.end .division`; `ProblemState` `.solved .first_ac .last_ac .wrong_before_ac .wrong_total .solved_in_contest .tried_in_contest .judged`; `make_key`, `split_key`, `problem_url`, `contest_url`, `GYM_MIN_ID`, `FAILED_VERDICTS`, `VERDICT_SHORT`. |
| `dojo/cf/snapshot.py` | `Snapshot`: `cfg handle user rating max_rating rank rating_history submissions problems contests archive group_codes group_names authenticated fetched_at loaded now_ts now today tz`; derived `states solved attempted_unsolved all_solved archive_solved ac_times ac_days`; `problem(key)`, `url(key)`, `contest_url(cid)`, `contest_name(cid)`, `training_name(cid)`, `local_date(ts)`, `solved_between(a, b)`, `require(*datasets)`. `load_snapshot(...)`, `ALL`. |
| `dojo/cf/metrics.py` | `comfort_rating(snap)`, `solved_ratings(snap, since_ts)`, `current_streak(days, today)`, `best_streak(days)`, `week_window(snap)`, `solved_this_week(snap)`, `daily_counts(snap, days)`, `weekly_counts(snap, weeks)`, `floor100`. **Use these; don't re-derive.** |
| `dojo/context.py` | `Ctx(args, cfg, term, state, offline, refresh)`, `ctx.snapshot(need=ALL)`. |
| `dojo/commands/__init__.py` | `add_command(sub, common, name, help, description=None, aliases=())`, `COMMANDS`. Each command module: `register(sub, common)` + `run(ctx) -> int`. |
| `dojo/drill/core.py` | `Topic`, `Question(prompt, expect, check, answer, solution, hint)`, `Verdict(ok, message, retry)`, `@register`, `load_topics()`, `parse_number`, `check_number`, `fmt_number`, `fmt_fraction`, `norm`, session runner, history. |
| `tests/fixtures.py` | `NOW` (Tue 6 Oct 2026 12:00 Cairo), `ts(days_ago, hour=)`, `prob()`, `sub()`, `contest()`, `rating_change()`, `make_snapshot()`, `TempHome`, `temp_state()`, `capture_term()`, `run_cli(argv, snap=, inputs=, home=)`. |

Rank colours come from `Term.rating()`; problem ratings use the same colours.

## 4. Modules and ownership

### A. Analytics — `dojo/cf/analysis.py`, `dojo/commands/status.py`, `dojo/commands/weak.py`, `tests/test_analysis.py`

```python
@dataclass
class Insight:
    priority: int          # higher = more important; status shows the top 3
    text: str              # one sentence, specific, with numbers, ends with an action when there is one

@dataclass
class Overview:
    handle: str; rating: int | None; max_rating: int | None; rank: str
    target: int; to_target: int | None              # target - rating (None if unrated)
    contests: int; rating_history: list[RatingChange]
    solved_total: int                               # len(snap.all_solved)
    solved_problemset: int; solved_groups: int      # contest_id < GYM_MIN_ID vs >=
    week_start: date; week_solved: int; week_goal: int
    streak: int; best_streak: int; active_today: bool
    last_ac: datetime | None
    daily: list[tuple[date, int]]                   # metrics.daily_counts(snap, 28)
    weekly: list[tuple[date, int]]                  # metrics.weekly_counts(snap, 12)
    verdicts: Counter                               # verdict -> count over all submissions
    wa_per_ac: float                                # WRONG_ANSWER count / OK count (0 if no OK)
    first_try_rate: float                           # solved problems with wrong_before_ac == 0 / solved
    comfort: int                                    # metrics.comfort_rating
    by_rating: dict[int, int]                       # solved count per rating (rated problems only)
    authenticated: bool
    insights: list[Insight]                         # sorted by priority, descending

def overview(snap: Snapshot) -> Overview
def render_status(ov: Overview, term: Term, *, compact: bool = False) -> str
    # compact=True: 2–3 lines for the home screen (rating → target bar, week x/goal, streak, top insight)

@dataclass
class TagStat:
    tag: str
    importance: float      # share of recent problemset problems in the practice band carrying the tag
    solved: int            # your solved problems with the tag (problemset-tagged problems only)
    expected: float        # importance * (your solved problems that have tags, in the band)
    failed_attempts: int   # failed judged submissions on problems with the tag
    attempts: int          # judged submissions on problems with the tag
    avg_rating: float | None
    focus: float           # ranking score, higher = practise this more

def tag_profile(snap: Snapshot, *, low: int | None = None, high: int | None = None) -> list[TagStat]
    # band defaults: [800, max(target_rating, comfort + 300)]; importance from problemset problems
    # with contest_id >= cfg.min_contest_id and rating in band, excluding '*special'. Sorted by focus desc.
def focus_tags(snap: Snapshot, k: int = 3) -> list[str]
    # top-k tags by focus among tags with importance >= 0.05 — used by `dojo today` to steer picks
```

**Focus score** must reward: high importance, low coverage (`solved / expected`), high fail rate on that tag; and be stable with
little data (smooth with a prior, e.g. `(solved + 1) / (expected + 1)`). Document the formula in a docstring. Tags are only known for
problemset problems (group problems mostly have no tags) — say so in `dojo weak` output.

**Insights** (rules, each only when true; examples of the kind wanted — compute real numbers):
- volume drop: "You've solved 4 problems in the last 3 weeks, down from 85 in the 3 weeks before. A small daily plan beats a big weekly one — `dojo today`."
- debugging: "318 wrong answers vs 270 accepted (1.18 per AC); 42 problems took 3+ tries. Before resubmitting, run `dojo stress`."
- inactivity: "No accepted problem for 10 days." ; streak alive: "3-day streak — solve one today to keep it."
- target: "453 rating to Pupil. Div. 3 rounds: solving A–C quickly usually gives a 1200+ performance."  (don't invent stronger claims)
- old compiler: only if any of the last 20 submissions used a 32-bit or GCC ≤ 9 compiler: "Your last submissions used C++17 (GCC 7-32), a 32-bit compiler — pick C++23 (GCC 14-64)."
- unauthenticated: "Only public submissions are visible — add CF_API_KEY/CF_API_SECRET to include group training."
- upsolve available (if any unsolved problem in a contest you took part in has rating ≤ comfort+500): "2227B (800) from your first Div. 3 is still unsolved — `dojo upsolve`."

**`dojo status`** (`--json` too): handle in rank colour, rating → target bar with "453 to Pupil", rated contests with deltas and a sparkline of ratings,
solved totals (problemset vs groups, by-rating mini histogram for 800…1600+), this week x/goal bar, streak/best, last AC ago,
28-day sparkline, verdict profile (AC, WA, TLE, RE, CE, WA per AC, first-try %), comfort rating, top insights.

**`dojo weak`** (`--json`, `--all` for every tag, `--band LOW-HIGH`): table tag · importance % · solved/expected · fail rate · focus bar; then
"Focus next: binary search, two pointers, …" with a one-line reason each; a note that group problems are untagged.

### B. Planning — `dojo/cf/recommend.py`, `dojo/cf/upsolve.py`, `dojo/commands/today.py`, `dojo/commands/skip.py`, `dojo/commands/upsolve.py`, `dojo/commands/retry.py`, `tests/test_planning.py`

```python
@dataclass
class PlanItem:
    key: str
    slot: str              # "warmup" | "core" | "stretch" | "java" | "upsolve" | "retry"
    rating: int | None
    focus_tag: str | None  # tag that steered the pick (a spoiler — shown only with --tags)

@dataclass
class Plan:
    day: date
    items: list[PlanItem]
    comfort: int
    rerolls: int
    created_at: float
    def to_json(self) -> dict ; @classmethod def from_json(cls, d) -> Plan

def build_plan(snap: Snapshot, *, day: date, comfort: int, focus: list[str], size: int,
               java_day: bool, exclude: set[str], rerolls: int = 0,
               extras: list[PlanItem] = ()) -> Plan                  # pure + deterministic
def todays_plan(snap: Snapshot, state: State, *, day: date | None = None, reroll: bool = False,
                focus: list[str] | None = None) -> Plan              # load or build+persist in state["plans"][iso]
def item_done(snap: Snapshot, item: PlanItem) -> bool               # solved (any AC; for "retry" re-solves: an AC after the plan day began)
def render_plan(plan: Plan, snap: Snapshot, term: Term, *, show_tags: bool = False, compact: bool = False) -> str

@dataclass
class UpsolveItem:
    key: str; contest_id: int; contest_name: str; index: str; rating: int | None
    attempted: bool; contest_time: int
def upsolve_queue(snap: Snapshot, comfort: int) -> list[UpsolveItem]

@dataclass
class RetryItem:
    key: str
    kind: str              # "unsolved" (failed, never AC) | "resolve" (hard-won, due for a from-scratch re-solve)
    wrong: int             # failed attempts (before the first AC, for resolve)
    last_time: int         # last submission time
    due: date | None       # resolve only
    stage: int             # resolve only: 0, 1, 2 → intervals 3, 10, 30 days
def retry_queue(snap: Snapshot, state: State, *, today: date | None = None) -> list[RetryItem]
```

**Plan algorithm (deterministic):**
- Candidates: `snap.problems` with a rating, `type == "PROGRAMMING"`, `contest_id >= cfg.min_contest_id`, no `*special` or `interactive` tag,
  `solved_count >= 300` (if known), not in `snap.states` (never touched) and not in `exclude`; also drop a candidate whose name equals
  (case-insensitive) the name of a touched problem in a contest within ±3 ids (Div. 1/Div. 2 twins).
- Slots by `size`: 1 → [core]; 2 → [core, stretch]; 3 → [warmup, core, stretch]; 4 → [warmup, core, core, stretch]; ≥5 → add core, then stretch alternately.
  Ranges with c = comfort: warmup [c−100, c] (never below 800), core [c+100, c+200], stretch [c+300, c+400] capped at target_rating+300.
  If a slot's range is empty after filters, widen by 100 each side (up to 3 times) before giving up on that slot.
- Weights within a slot: newer contests preferred (linear in contest_id across the pool, ×1 → ×3); Div. 3 / Div. 4 / Educational rounds ×1.5
  (from `snap.contests[cid].division`); popularity `log10(solved_count)` factor. Core slot *i* requires focus tag `focus[i]` when such a candidate exists.
- RNG: `random.Random(f"{handle}:{day.isoformat()}:{rerolls}")` → same plan all day, different after a reroll. Never pick a key twice.
- `java_day` (cfg.java_weekdays contains the weekday): add slot "java": rating in [800, max(800, c−100)], tags preferring implementation/strings/math/sortings — "solve this one in Java".
- Extras added by `todays_plan`: the top upsolve item (if any) as slot "upsolve", and the most urgent retry item (due re-solve first, else most recent unsolved) as "retry".
- `exclude` = keys recommended in the last 14 days' plans that are still unsolved (variety) + keys skipped via `dojo skip`.
- Persist: `state["plans"][iso] = plan.to_json()`; keep only the last 60 days. A stored plan is reused as is (only completion marks change). `--reroll` keeps items already done, replaces the rest.

**`dojo today`**: header "Tue 06 Oct · comfort 900 · 2/5 done"; one line per item: ✓/○, slot label, `term.link(key + " " + name, url)`, rating in rank colour,
(tags only with `--tags`); java item says "in Java: dojo new 2227A --java"; footer hints (`dojo skip <id>`, `dojo stress`). Flags: `--reroll`, `--tags`,
`--date YYYY-MM-DD` (view a past plan; never create a plan for the past), `--json`. `render_plan(compact=True)`: one short line per item for the home screen.

**`dojo skip <id> [--reason R]`**: removes an unsolved item from today's plan, adds it to `state["plans"]["_skipped"]` (list), and fills the slot with the next pick (same slot rules).

**Upsolve:** contests = rated contests (`snap.rating_history`) ∪ public contests where the user has an in-contest submission. For each, problems from
`snap.problems` with that contest_id. Include unsolved problems with rating ≤ comfort + 500, or (unrated) index position ≤ best solved index + 2.
Order: newest contest first, then index. **`dojo upsolve`** groups by contest (name, date, your rank/delta if rated), marks problems you tried in contest, `--json`, `--all` (no rating cap).

**Retry:** "unsolved" = `snap.attempted_unsolved`, newest first (group problems included; use `snap.url` — it knows group codes).
"resolve" = solved problems with `wrong_before_ac >= 2` whose first AC was within the last 120 days, scheduled at first_ac_date + 3 / 10 / 30 days (stage 0/1/2).
A stage completes automatically when the snapshot has a newer AC for that problem on/after its due date, or manually with `dojo retry --done <id>`; after stage 2 it's retired.
Store schedule in `state["resolve"][key] = {"stage": int, "due": iso, "done": [iso, ...]}`. **`dojo retry`** shows due/overdue re-solves first, then unsolved;
`--all` shows not-yet-due re-solves; `--done KEY`; `--json`.

### C. Local judge — `dojo/run/__init__.py`, `dojo/run/lang.py`, `dojo/run/judge.py`, `dojo/run/cph.py`, `dojo/run/stress.py`, `dojo/gen.py`, `dojo/run/templates/brute.cpp`, `dojo/run/templates/gen.py`, `dojo/commands/test.py`, `dojo/commands/stress.py`, `tests/test_run.py`

```python
# lang.py
@dataclass
class Program:
    src: Path; lang: str            # "cpp" | "c" | "java" | "py"
    def cmd(self) -> list[str]      # argv to run (after build)
def build(src: Path, *, debug: bool = False, std: str = "c++23") -> Program
    # C++: g++ -std=c++23 -O2 -Wall -Wextra -Wshadow -DLOCAL; debug adds -g -fsanitize=address,undefined -D_GLIBCXX_DEBUG
    # cached by sha256(source + flags + compiler version) in cache_dir()/build/; Java: javac into a cache dir, run the class with main
    # (detect it: a top-level class declaring `static void main`; non-public `class Main` must work); Python: sys.executable.
    # Compile errors → DojoError with the compiler's first ~30 lines.
# judge.py
@dataclass
class RunResult:
    stdout: str; stderr: str; code: int; seconds: float; timed_out: bool; signal: str | None
def run(prog: Program, stdin: str, *, tl: float = 2.0, args: list[str] = ()) -> RunResult    # own process group, killed on timeout
def compare(out: str, ans: str, *, mode: str = "tokens", eps: float = 1e-6) -> tuple[bool, str]
    # tokens (whitespace-insensitive), exact (line by line, trailing spaces ignored), float (numbers within eps abs or rel); message = first difference
# cph.py
def cph_tests(src: Path) -> list[tuple[str, str]] | None     # find .cph/.<name>_<hash>.prob next to src whose srcPath matches
# stress.py
@dataclass
class StressResult: ok: bool; iterations: int; failing_input: str | None; expected: str | None; got: str | None; reason: str | None
def stress(sol: Program, brute: Program, gen: Program, *, n: int, tl: float, mode: str, eps: float,
           checker: Program | None = None, seed0: int = 1, on_progress=None) -> StressResult
```
- Generators get the seed as argv[1] (`gen 17` → test 17) and print one test to stdout. `dojo/gen.py` is a helper library users import from their
  Python generators (`from dojo.gen import *`): `seed_from_argv()`, `rint(lo, hi)`, `rarray(n, lo, hi)`, `perm(n)`, `rstring(n, alphabet)`, `tree_edges(n)`,
  `graph_edges(n, m, connected=False)`, `distinct(n, lo, hi)`, plus `out(*rows)` to print. Python generators run with `sys.executable`, so the import works.
- A checker gets `checker input output answer` paths; exit code 0 = accepted (testlib convention).
- **`dojo test <file> [inputs...]`**: build, run on CPH samples (or given `.in` files with matching `.out`/`.ans`, or stdin), show each verdict
  (AC/WA/TLE/RE with time), first difference for WA, exit 1 if any fail. `--tl`, `--debug`, `--float EPS`, `--exact`.
- **`dojo stress <sol> [--brute F] [--gen F] [-n 500] [--tl 2] [--debug] [--checker F] [--float EPS]`**: discovers `brute.*`/`<stem>_brute.*` and
  `gen.*`/`<stem>_gen.*` next to the solution when not given. On the first mismatch, crash or timeout: save `stress/fail.in`, `fail.out` (yours), `fail.ans`
  (brute) next to the solution, print the input (truncated to ~30 lines), the first difference, and the command to re-run (`dojo test sol.cpp stress/fail.in`).
  Progress on one updating line (stderr, only on a TTY). `--init` writes `brute.cpp` (his template + "// brute force: simplest correct solution" comment) and
  `gen.py` (from templates, using dojo.gen) next to the solution unless they exist. Explain in `--help` *why*: WA without a failing test is the #1 time sink.
- Default limits: tl 2 s for the solution; brute gets 10× tl. Ctrl-C prints the iteration count and exits 130.

### D. Contests, scaffold, Java — `dojo/cf/contests.py`, `dojo/commands/contests.py`, `dojo/commands/new.py`, `dojo/commands/java.py`, `dojo/run/templates/solution.cpp`, `dojo/run/templates/Main.java`, `tests/test_contests.py`, `tests/test_scaffold.py`

```python
@dataclass
class Upcoming:
    contest: Contest
    start: datetime; end: datetime        # local (cfg.tz)
    division: str | None
    recommended: bool                     # Div. 3, Div. 4, Educational, Div. 2 (and "Div. 1 + Div. 2"): yes; Div. 1 alone: no
    clashes: list[ClassSlot]              # class slots overlapping the contest (same weekday, overlapping times; handle contests crossing midnight)
    late: bool                            # starts between 00:00 and 07:00 local
def upcoming(snap: Snapshot, *, days: int = 14) -> list[Upcoming]       # phase BEFORE (and CODING, marked "running"), sorted by start
def render_upcoming(items: list[Upcoming], term: Term, *, compact: bool = False) -> str
def to_ics(items: list[Upcoming], now: datetime) -> str                # RFC 5545, UTC times, UID per contest, 30-min VALARM, CRLF line endings
```
- **`dojo contests`** `[--days N] [--all] [--ics FILE] [--json]`: table: when (local, 'Wed 07 Oct 17:35'), in (countdown '1d 13h'), length, name (link to
  contests page), markers: ★ recommended, ⚠ clash with "<what>", ☾ late. Default hides Div. 1-only rounds (`--all` shows them). Footer: next recommended
  round in plain words. `render_upcoming(compact=True)`: one line for the next recommended round.
- **`dojo new <problem> [--java] [--dir D] [--name N] [--open] [--force]`**: problem as key `2227A`, `2227 A`, or any Codeforces problem URL
  (contest/problemset/gym/group). File name like CPH's: `<Index>_<Name_With_Underscores>.cpp` (e.g. `A_Koshary.cpp`), names from the problemset cache
  (offline-capable; `--name` for group problems). Header comment: `// <key> <name> — <url>`. C++ body = `cfg.template` file if set, else
  `templates/solution.cpp` (exactly his template). `--java` writes `<Index>_<Name>.java` with a fast-I/O CP template whose class is a **non-public** `class Main`
  (compiles under any file name with javac; Codeforces accepts it). Never overwrite without `--force`. `--open` runs `cfg.editor <file>`. Print the path.
- `templates/Main.java`: BufferedReader + StringTokenizer fast reader (nextInt/nextLong/next/nextLine), PrintWriter with flush at end, `long` by default,
  and a comment on the `Arrays.sort(int[])` anti-quicksort hack (sort Integer[]/long boxed or shuffle first). Must compile with JDK 21 and pass a small sample.
- **`dojo java`** `[topic]`: a C++ → Java cheat sheet for CP, for someone who knows C++ and is new to Java (his CIS 201 course). Sections: I/O, types &
  overflow (`long`, `int` division, `Math.floorMod`), strings (immutable, `StringBuilder`, `equals` vs `==`), arrays & sorting (pitfall above, comparators),
  collections map (vector→ArrayList, map→TreeMap, unordered_map→HashMap, set→TreeSet, priority_queue→PriorityQueue (**min**-heap by default), pair→record/long[]),
  `Integer` caching pitfall (`==` on boxed values outside −128…127), recursion depth (run in a Thread with a big stack), common CE/RE causes on Codeforces.
  Every Java snippet must be verified: tests compile all snippets with `javac` (skip the test with a message if javac is missing).

### E. Logic drills — `dojo/drill/boolexpr.py`, `dojo/drill/logic.py`, `tests/test_logic.py`

`boolexpr.py` — expression engine, no topic code:
- Parser for both notations. Variables: one letter (A–Z, a–z), adjacency = AND in uppercase logic-design style (`AB'C`). NOT: postfix `'`,
  prefix `~ ! ¬ not`. AND: adjacency, `* · & ∧ and`. OR: `+ | ∨ or`. XOR: `⊕ xor`. Implies: `-> → => implies`. Iff: `<-> ↔ <=> iff`. Constants `0 1`.
  `^` is rejected with "ambiguous: write & for AND or xor for XOR". Precedence: NOT > AND > XOR > OR > IMPLIES (right-assoc) > IFF. Clear error messages with the position.
- `Expr` AST with `eval(env)`, `vars()`, `to_str(style="design"|"discrete")`; `truth_table(expr, vars)`; `minterms(expr, vars)`.
- `minimize(n, minterms, dontcares) -> list[Implicant]`: Quine–McCluskey prime implicants + essential PIs + **Petrick's method** for an exactly minimal cover
  (fewest terms, then fewest literals); deterministic tie-break. `Implicant` renders as `A'BD`. Also `minimal_pos` via the complement.
- `is_sop(expr)`, `cost(expr) -> (terms, literals)`.
- Exhaustively test: every 3-variable function (256) and every 4-variable function with ≤ 6 minterms plus a random sample of others: the cover equals the function on the care set, and its cost equals a brute-force minimum (search over subsets of prime implicants).

`logic.py` — topics (register all with `@register`):
| key | course | asks | answer format |
|---|---|---|---|
| `truth` | BSC 201 | classify a proposition (2–4 vars; →, ↔ from level 2) as tautology / contradiction / contingency; or give its final truth-table column | word (t/c/contingency accepted) or T/F string, rows in Rosen order (T first: TT, TF, FT, FF) |
| `equiv` | BSC 201 | are these two propositions equivalent? Pairs from the standard laws (De Morgan, contrapositive, implication ≡ ¬p∨q, distributive, absorption, exportation, biconditional) and near-misses (converse, inverse, wrong De Morgan) ~50/50 | yes/no |
| `minterms` | CIS 203 | list Σm of an expression (3–4 vars) | comma/space-separated numbers, any order |
| `kmap` | CIS 203 | minimal SOP for Σm(...) + d(...) (3 vars L1, 4 vars L2, 4 vars + don't cares L3) | expression |
| `simplify` | CIS 203 | simplify an expression to minimal SOP | expression |

- Grading for `kmap`/`simplify`: parse error → retry; not equal on the care set → wrong, name a minterm where it differs ("you output 1 for m5 = A'BC'D"); equal but not SOP →
  retry with "write it as a sum of products"; SOP but not minimal → wrong with "correct function, but 4 terms / 10 literals; minimum is 3 / 7".
- Solutions: K-map drawn in text with Gray-code order (rows AB 00 01 11 10, cols CD 00 01 11 10; 3-var: rows A, cols BC), cells 1/0/X, then prime implicants
  with the minterms each covers, essential PIs, the chosen cover. Truth tables with intermediate columns for `truth`/`equiv`; for a non-equivalent pair, the counterexample row.
- `solve` syntax: `kmap`: `m(0,2,5,7) d(1)` with optional `vars=ABCD`, or an expression; `truth`: a proposition; `equiv`: `p -> q ; ~q -> ~p`; `minterms`/`simplify`: an expression.

### F. Number & statistics drills — `dojo/drill/numbers.py`, `dojo/drill/stats.py`, `tests/test_numbers.py`, `tests/test_stats.py`

| key | course | asks |
|---|---|---|
| `base` | CIS 203 | convert between bases 2, 8, 10, 16. L1 small ints dec↔bin; L2 any pair up to 12 bits; L3 fixed-point fractions (e.g. 10.625 → 1010.101) |
| `twos` | CIS 203 | n-bit two's complement: encode a negative, decode a pattern, A ± B with the n-bit result, overflow yes/no, range of n bits; L3 adds sign-magnitude and 1's complement |
| `freq` | CIS 208 | from raw categorical/discrete data (like the lecture's blood types A B O AB, n = 28): frequency, relative %, cumulative %, pie angle 360·f/n |
| `center` | CIS 208 | mean, median, mode of a small data set; L3 mean from a frequency table |
| `spread` | CIS 208 | range, SS = Σ(X−X̄)², variance and standard deviation — **the question says population (σ², ÷N) or sample (s², ÷(n−1))** |
| `zscore` | CIS 208 | z = (X−μ)/σ, raw score from z, which of two scores is relatively better |

- Exact arithmetic with `fractions.Fraction`; ask for answers "to 2 decimal places" and grade with `core.check_number` (decimals=2). Percentages use `pct=True`.
- Answer parsing for bases: ignore spaces/underscores, accept `0x`/`0b`/`0o` prefixes and lower/upper case hex; demand the exact width when the question says "8-bit".
- Solutions show the method a student writes on paper: repeated division with a remainder column; positional expansion; 3-/4-bit grouping; invert-and-add-1 with
  the carry row; column addition with carries and the overflow rule (carry into MSB ≠ carry out of MSB); the frequency table in the lecture's format
  (Class | Frequency | Relative % | Cumulative %); the SS table (X, X−X̄, (X−X̄)²).
- Pick numbers that give clean-ish answers at L1 and realistic exam numbers at L3. Never generate a question whose answer is ambiguous (e.g. a multimodal mode question
  must accept all modes, or avoid them).
- `solve` syntax: `base`: `255 to 16`, `0x1F to 2`, `101.101 b2 to 10`; `twos`: `-45 bits=8`, `11010110 bits=8`, `-45 + 23 bits=8`, `100 - 27 bits=8`;
  `freq`/`center`/`spread`/`zscore`: the data list, e.g. `spread 4 8 6 5 3 sample`, `zscore x=72 mean=65 sd=5`.

## 5. Terminal UX

- Lead with the number that matters. One idea per line. Align with `term.table` / `term.kv`. Section titles with `term.section`.
- Problem references: `term.link(f"{key} {name}", snap.url(key))` with the rating via `term.rating(r)`.
- Width: assume 80–120 columns; truncate long names with `truncate()` before styling.
- `--json` output: `json.dumps(obj, indent=2, default=str)` to stdout, nothing else on stdout.
- Hints at the bottom in `term.muted(...)`, at most two lines.

## 6. Tests

- `python3 -m unittest discover -s tests -t .` from the repo root must pass, fast (< 20 s total), offline.
- Test pure logic directly with `make_snapshot(...)`; test commands with `run_cli([...], snap=...)`.
- Cover edge cases: empty data, unrated user, no API key (`authenticated=False`), offline missing data, timezone/day boundaries, small terminals.
- Before finishing: run your tests, run the full suite, and exercise your commands manually with `python3 -m dojo --offline …` on the real cache.
