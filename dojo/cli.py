"""dojo — Codeforces coach + course drills.

Codeforces
  dojo                 overview: rating, streak, today's plan, next contest
  dojo today           today's practice problems (dojo skip <id> swaps one out)
  dojo status          rating, progress to Pupil, weekly goal, verdict profile
  dojo weak            which tags to practise, from your own attempts
  dojo upsolve         problems from your contests you haven't solved yet
  dojo retry           attempted-but-unsolved, and hard-won problems due for a re-solve
  dojo contests        upcoming rounds in Cairo time, with class clashes flagged
Local judge
  dojo new <id>        create a solution file from your template (--java for CIS 201 practice)
  dojo test <file>     run a solution on its CPH samples or your own .in files
  dojo stress <file>   compare against a brute force on random tests until they differ
  dojo java            C++ -> Java cheat sheet for competitive programming
Course drills (CIS 203, BSC 201, CIS 208)
  dojo drill [topic]   practise with instant checking and worked solutions
  dojo solve <topic>   check your own work step by step
Other
  dojo web             the whole thing in your browser (local server)
  dojo report          HTML dashboard     dojo bar     status-bar JSON
  dojo sync            refresh data       dojo init    write the config file
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from dojo import __version__, config
from dojo.commands import COMMANDS
from dojo.context import Ctx
from dojo.errors import DojoError
from dojo.state import State
from dojo.term import Term


def build_parser() -> argparse.ArgumentParser:
    # Global flags work before or after the command. In the subparser copy they default to
    # SUPPRESS so a subcommand doesn't overwrite a value given before it.
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("global options")
    g.add_argument("--offline", action="store_true", default=argparse.SUPPRESS,
                   help="never touch the network; use cached data")
    g.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS,
                   help="refetch Codeforces data even if the cache is fresh")
    g.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="plain output")

    ap = argparse.ArgumentParser(prog="dojo", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="never touch the network; use cached data")
    ap.add_argument("--refresh", action="store_true", help="refetch Codeforces data even if fresh")
    ap.add_argument("--no-color", action="store_true", help="plain output")
    ap.add_argument("--config", type=Path, help="config file (default ~/.config/dojo/config.toml)")
    ap.add_argument("--version", action="version", version=f"dojo {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    for name in COMMANDS:
        importlib.import_module(f"dojo.commands.{name}").register(sub, common)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        args.func = importlib.import_module("dojo.commands.home").run
    term = Term(color=False if args.no_color else None)
    state = State()
    try:
        cfg = config.load(args.config)
        ctx = Ctx(args=args, cfg=cfg, term=term, state=state, offline=args.offline, refresh=args.refresh)
        return int(args.func(ctx) or 0)
    except DojoError as e:
        term.err(term.s("dojo: ", "bad", "bold") + str(e))
        return 1
    except KeyboardInterrupt:
        term.err("")
        return 130
    except BrokenPipeError:
        sys.stderr.close()          # `dojo upsolve | head` — not an error
        return 0
    finally:
        try:
            state.save()
        except OSError as e:
            term.warn(f"couldn't save state: {e}")
