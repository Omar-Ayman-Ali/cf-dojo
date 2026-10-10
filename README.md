# dojo

A personal training tool for two goals:

1. **Codeforces**: reach your target rating (e.g. 1200 Pupil or 1400 Specialist). dojo reads your submission history, including private-group submissions, and tells you what to solve today, which tags you're weak at, what to upsolve, and what to re-solve. It also includes a local judge with stress testing.
2. **University courses**: unlimited generated practice with instant checking and worked solutions for Logic Design (Boolean algebra, Karnaugh maps, two's complement), Discrete Mathematics (truth tables, logical equivalence) and Statistical Analysis (descriptive statistics, distributions, z-scores).

You can use it in the terminal (`dojo …`) or in the browser (`dojo web`). Python 3.11+, standard library only, no dependencies.

## Install

```sh
# Clone the repository
git clone https://github.com/<your-username>/dojo.git
cd dojo

# Install with uv (recommended) or pip
uv tool install -e .    # puts `dojo` on your PATH
# or: pip install -e .

dojo init               # writes ~/.config/dojo/config.toml
dojo sync               # first download of your Codeforces data
```

Because it's an editable install, changes to the source take effect immediately.

Without installing: `python3 -m dojo <command>` from this directory.

## Daily use

```sh
dojo            # home: rating, streak, today's plan, next contest, a suggested drill
dojo today      # today's problems
dojo web        # the same thing in your browser
```

## Commands

### Codeforces coach

| Command | What it does |
|---|---|
| `dojo` | Overview: rating, progress to target, this week, today's plan, next contest, suggested drill. |
| `dojo today` | Today's plan, built around your *comfort rating* (75th percentile of what you solved in the last 90 days). Slots: **warm-up** (c-100…c), **core** (c+100…c+200, steered to weak tags), **stretch** (c+300…c+400), **java** (easy, on `java_days`), **upsolve**, **retry**. The plan stays fixed for the day and items tick off on AC. `--reroll`, `--tags` (spoilers), `--date`, `--json`. |
| `dojo skip <id\|n>` | Swap one unsolved item for the next pick under the same rules. The skipped problem is never planned again. `--reason`. |
| `dojo status` | Rating and gap to target, rated rounds, solves by rating, week vs goal, streaks, verdict profile, the three most useful things to change. `--json`. |
| `dojo weak` | Which tags to practise: share at your level × (0.5 + fail rate) / coverage. `--all`, `--band 900-1400`, `--json`. |
| `dojo upsolve` | Unsolved problems from contests you took part in, newest first, capped at comfort + 500. `--all`, `--json`. |
| `dojo retry` | **Re-solve**: problems that took 2+ failed attempts, due again at 3, 10 and 30 days after the first AC. **Unsolved**: submitted and never accepted. `--done <id>` records a re-solve. `--all`, `--json`. |
| `dojo contests` | Upcoming rounds in your configured time. ★ suits you, ⚠ clashes with a class/commitment in your schedule, ☾ starts late at night. `--days N`, `--all` (Div. 1), `--ics FILE` (calendar export), `--json`. |

### Local judge

| Command | What it does |
|---|---|
| `dojo new 2227A` | Creates `A_Solution.cpp` (CPH naming) from your template, with a header that links the problem. `--java` writes `A_Solution.java` with `class Main` and fast I/O. Also `--dir`, `--name` (for group/gym problems), `--open`, `--force`. Accepts `2227 A` or a problem URL. |
| `dojo test file.cpp` | Compiles and runs on the CPH samples from `.cph/`, or on `.in` files you name (checked against `.out`/`.ans`). Reports AC/WA/TLE/RE. `--debug` adds sanitizers and the checked STL. Also `--tl`, `--float EPS`, `--exact`, `--checker`. Works with C++, C, Java and Python. |
| `dojo stress file.cpp` | For a WA when you can't find the failing test. dojo runs your solution and a slow brute force on random tests until their answers differ, then saves the input to `stress/fail.in`. `--init` writes `brute.cpp` and `gen.py` to start from. Generators can `from dojo.gen import *`. Also `-n`, `--seed`, `--debug`, `--checker`. |
| `dojo java [topic]` | C++ → Java cheat sheet for competitive programming: io, types, strings, arrays, collections, boxing, recursion, errors. |

### Course drills

| Command | What it does |
|---|---|
| `dojo drill` | Lists topics with your accuracy and suggests one. |
| `dojo drill <topic…>` | A practice session. At the prompt: `?` gives a hint, `!` shows the solution, `q` quits. `-n`, `-l 1-3` (level), `--seed`, `--explain`. You can also pass a course code (`dojo drill 203`) or `mix`. |
| `dojo solve <topic> <problem>` | Works a homework problem step by step. `--check ANSWER` only grades your answer, and `--reveal` adds the solution. `dojo solve` alone lists the input syntax. |

Topics:

- **Logic Design**: `base` (bases 2/8/10/16, fractions at level 3), `twos` (n-bit two's complement, add/subtract, overflow), `minterms`, `kmap` (minimal SOP with don't-cares), `simplify`
- **Discrete Math**: `truth` (tautology/contradiction/contingency), `equiv` (equivalence laws and near-misses)
- **Statistics**: `freq` (frequency, relative %, cumulative %, pie angles), `center` (mean/median/mode), `spread` (range, SS, variance, SD), `zscore`

```sh
dojo solve kmap 'm(0,2,5,7) d(1)'
dojo solve twos -45 + 23 bits=8
dojo solve spread 4 8 6 5 3 sample
dojo solve truth '(p -> q) & ~q -> ~p'
```

### Other

| Command | What it does |
|---|---|
| `dojo web` | Local web UI at `http://127.0.0.1:8765`, opened in your browser. It has every page above plus a judge page and a stats page with charts. `--port`, `--no-open`. |
| `dojo report` | One-file HTML dashboard in your data directory: rating history, weekly solves, activity heatmap, verdicts, weak tags, plan, upsolve queue. `--open`. |
| `dojo bar` | One JSON line for a waybar custom module (`CF 1200 · 0/10 wk · 0/6 today`). Offline by default. Run `dojo bar --help` for the waybar snippet. |
| `dojo sync` | Refresh Codeforces data now. `--quick` refreshes only your profile, rating and submissions. |
| `dojo init` | Write the config file. `--force` overwrites. |

Global flags, valid before or after any command: `--offline` (cache only), `--refresh` (refetch
even if fresh), `--no-color`, `--config FILE`.

## The web UI

`dojo web` starts a server on your machine. A hosted site couldn't do this job: the app needs your
cached data, your API key and your compiler. The server:

- listens on `127.0.0.1` only, so other machines can't reach it;
- requires a per-run token that's embedded in the page, and checks the `Host` header. Other websites
  open in your browser can't call the API, which matters because the API compiles and runs files.

Pages: Home, Today, Upsolve, Re-solve, Weak tags, Contests, Stats, Judge, Drills, Solve, Java sheet.
Dark and light themes, phone-width layout, no CDN (it works offline).

## Configuration

`~/.config/dojo/config.toml` (written by `dojo init`). Every key is optional.

- `[codeforces]`: `handle`, `target_rating`, `env_file` (holds `CF_API_KEY` / `CF_API_SECRET`.
  Signed calls include your private-group submissions), `archive`.
- `[training]`: `timezone`, `week_start` (Mon or Sat), `weekly_goal`, `plan_size`, `java_days`,
  `min_contest_id`, `hide_tags`.
- `[workspace]`: `dir` (~/codeforces), `template`, `editor`, `cph_dirs`.
- `[[schedule]]`: your weekly classes (`day`, `start`, `end`, `what`). `dojo contests` warns about clashes.

Files: config in `~/.config/dojo/`, cache in `~/.cache/dojo/`, state (plans, re-solves, drill
history) in `~/.local/share/dojo/state.json`. `XDG_*` variables are honoured. `DOJO_HOME` puts all
three under one directory.

### Background refresh (optional)

`contrib/` has a systemd user timer that runs `dojo sync --quick` every 30 minutes from 08:00 to 23:00:

```sh
cp contrib/dojo-sync.{service,timer} ~/.config/systemd/user/
systemctl --user enable --now dojo-sync.timer
```

## Development

```sh
python3 -m unittest discover -s tests     # unit tests, no network
python3 -m dojo --offline <command>       # manual runs against cached data
```

`DESIGN.md` is the contract between modules: who owns which file and each public API. Layout:

```
dojo/cf/        Codeforces: API client + cache, snapshot, metrics, analysis, planning, upsolve, contests
dojo/run/       local judge: languages, judge, CPH samples, stress; templates/
dojo/drill/     drill framework (core), boolean minimiser, logic / number / stats topics
dojo/commands/  one module per CLI command
dojo/web/       server, JSON API, static frontend
contrib/        systemd timer for background sync
tests/          unit tests (fixtures.py builds fake snapshots)
```

## License

This project is licensed under the [MIT License](LICENSE).
The bundled Archivo font is licensed under the [SIL Open Font License](dojo/web/ARCHIVO-OFL.txt).
