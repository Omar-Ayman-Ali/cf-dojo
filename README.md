# Dojo (Competitive Programming Coach and Course Drill System)

**Live Demo:** Not deployed (local execution only)

A local-first training engine that combines Codeforces submission analysis, daily problem planning, automated stress testing, and course-level computer science practice drills.

![Language](https://img.shields.io/badge/Language-Python_3.11+-blue?style=flat-square)
![Dependencies](https://img.shields.io/badge/Dependencies-Zero_External-brightgreen?style=flat-square)
![Type](https://img.shields.io/badge/Type-CLI_%26_Local_Web-orange?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## Table of Contents
- [About](#about)
- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Run Locally](#run-locally)
- [Project Structure](#project-structure)

---

## About
Dojo is a developer utility designed to systematize competitive programming practice and reinforce core computer science fundamentals without external cloud services. The application reads Codeforces submission history to construct deterministic daily training plans, identify topic weaknesses, and run local differential stress testing against brute-force solutions. It provides an offline-first workflow accessible through both an interactive terminal interface and a zero-dependency local web dashboard.

---

## Architecture
The system operates entirely on the local host with three primary subsystems coordinated by a shared domain layer:

- **Codeforces Analytics Engine (`dojo/cf/`)**: Fetches and caches Codeforces user statistics and submissions using rate-limited HTTPS requests. When optional signed API credentials are provided, it ingests private-group submissions to track real problem coverage. The recommendation engine derives a rolling comfort rating to schedule daily problem sets balanced across warm-up, core focus tags, stretch goals, and spaced-repetition re-solves.
- **Local Judge and Stress Runner (`dojo/run/`)**: Manages solution compilation and execution for C++, C, Java, and Python. It parses sample inputs from Competitive Programming Helper (.cph) configuration files and runs differential stress tests against user-supplied brute-force implementations and test generators.
- **Course Drill Generator (`dojo/drill/`)**: Implements mathematical problem synthesis and verification algorithms, including a Quine-McCluskey boolean minimizer with Petrick's method, two's complement arithmetic verification, truth table evaluators, and descriptive statistical metrics.
- **Local Web Server (`dojo/web/`)**: Runs a lightweight HTTP server on 127.0.0.1 using standard library primitives. The server enforces host validation and requires a cryptographically random per-run token embedded into the served HTML to protect the local compilation API against Cross-Site Request Forgery (CSRF) and DNS rebinding attacks.

---

## Features
- **Daily Training Scheduler**: Generates fixed daily problem plans matched to rolling comfort ratings with slots for warm-up, core weaknesses, stretch goals, and spaced-repetition reviews.
- **Weakness Analysis**: Identifies underperforming problem tags by cross-referencing failure rates and solved counts against expected difficulty distributions.
- **Spaced-Repetition Queue**: Automatically schedules re-solve reminders at 3, 10, and 30 day intervals for problems requiring multiple attempts.
- **Contest Tracker**: Displays upcoming Codeforces rounds with countdowns, clash detection against configured class timetables, and iCalendar export.
- **Local Code Scaffolding**: Generates problem template files in C++ or Java with preconfigured headers, fast I/O, and problem links.
- **Local Test Runner**: Executes solutions against sample inputs from .cph directories and custom test cases with configurable time limits and sanitizers.
- **Differential Stress Testing**: Runs candidate solutions against brute-force implementations using randomized generators to isolate minimal failing inputs.
- **Logic Design Drills**: Generates practice problems with worked step-by-step solutions for number base conversions, two's complement, minterm expansions, and Karnaugh maps.
- **Discrete Math Drills**: Synthesizes propositional logic problems covering truth tables, tautologies, and equivalence laws.
- **Statistics Drills**: Generates practice questions for frequency distributions, measures of central tendency, dispersion, and standard scores.
- **Local Web Dashboard**: Provides a responsive, dependency-free web dashboard with SVG charts, interactive judge controls, and topic drill interfaces.
- **Waybar Integration**: Outputs single-line JSON metrics for Linux desktop status bars.

---

## Tech Stack
- **Languages**: Python (>= 3.11), Modern C++, Java, Vanilla JavaScript (ES2022)
- **Frameworks & Runtimes**: Python Standard Library (no third-party dependencies)
- **Web Frontend**: Native HTML5, CSS3 with CSS variables and SVG charts, Vanilla JavaScript
- **Supported Compilers**: GCC (g++), Clang, OpenJDK (javac / java)
- **Data & Cache**: Local filesystem storage using TOML configurations and JSON state snapshots
- **Security Protocols**: HMAC token authentication, DNS rebinding mitigation, localhost isolation

---

## Run Locally

### Prerequisites
- Python >= 3.11
- C++ compiler (`g++` or `clang++`) or Java JDK (`javac` / `java`) for local judging
- Git for source management
- `uv` (recommended) or `pip` for package installation

### Installation
Clone the repository:
```bash
git clone https://github.com/<your-username>/dojo.git
cd dojo
```

Install the package in editable mode:
```bash
uv tool install -e .
# Alternatively with pip:
# pip install -e .
```

Initialize the configuration file:
```bash
dojo init
```

Configure your Codeforces handle in `~/.config/dojo/config.toml`:
```toml
[codeforces]
handle = "your_handle"
target_rating = 1200
```

### Execution
Synchronize Codeforces submission history:
```bash
dojo sync
```

View the daily practice plan in your terminal:
```bash
dojo today
```

Start the local web dashboard:
```bash
dojo web
```

Run interactive course drills:
```bash
dojo drill logic
dojo drill stats
```

Execute unit tests:
```bash
python3 -m unittest discover -s tests
```

---

## Project Structure
```text
.
├── contrib/
│   ├── dojo-sync.service          # Systemd service unit for background data synchronization
│   └── dojo-sync.timer            # Systemd timer unit for scheduled updates
├── dojo/
│   ├── cf/                        # Codeforces API client, cache, metrics, and recommenders
│   │   ├── analysis.py            # Rating and performance analytics
│   │   ├── api.py                 # Rate-limited Codeforces API client
│   │   ├── cache.py               # Local JSON response caching layer
│   │   ├── contests.py            # Contest tracking and calendar generation
│   │   ├── metrics.py             # Rating progression and streak calculations
│   │   ├── model.py               # Domain dataclasses for submissions and problems
│   │   ├── recommend.py           # Daily problem plan selection engine
│   │   ├── snapshot.py            # Multi-dataset snapshot loader
│   │   └── upsolve.py             # Spaced-repetition and upsolve queue models
│   ├── commands/                  # CLI subcommands implementation
│   ├── drill/                     # Computer science course drill generators
│   │   ├── boolexpr.py            # Boolean parser and Quine-McCluskey minimizer
│   │   ├── core.py                # Topic registry and drill session runner
│   │   ├── logic.py               # Logic design problem generators
│   │   ├── numbers.py             # Number representation and base conversion drills
│   │   └── stats.py               # Statistics problem generators
│   ├── run/                       # Local judge, test runner, and stress tester
│   │   ├── templates/             # Starter templates for C++, Java, and stress generators
│   │   ├── cph.py                 # Competitive Programming Helper (.cph) test parser
│   │   ├── judge.py               # Execution result comparison and verdict evaluation
│   │   ├── lang.py                # Compiler orchestration for C++, C, Java, and Python
│   │   └── stress.py              # Differential stress-testing engine
│   ├── web/                       # Local web dashboard
│   │   ├── static/                # Vanilla HTML, CSS, JS, and self-hosted fonts
│   │   ├── api.py                 # JSON API endpoints shared with CLI --json
│   │   └── server.py              # Single-host HTTP server with token authentication
│   ├── cli.py                     # Main argument parser and command dispatcher
│   ├── config.py                  # TOML configuration loader and defaults
│   ├── context.py                 # Execution context container
│   ├── paths.py                   # XDG-compliant path resolver
│   ├── state.py                   # Persistent state manager
│   ├── term.py                    # Terminal formatting and ANSI styling
│   └── timeutil.py                # Timezone and date manipulation helpers
├── tests/                         # Comprehensive offline unit test suite (270 tests)
├── .gitignore                     # Git tracking exclusions
├── DESIGN.md                      # Architecture specifications and component contracts
├── LICENSE                        # MIT license
└── pyproject.toml                 # Package definition and console script entrypoints
```
