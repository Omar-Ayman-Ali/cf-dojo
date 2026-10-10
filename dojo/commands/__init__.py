"""Subcommands. Each module defines register(sub, common) and run(ctx) -> int.

    def register(sub, common):
        p = add_command(sub, common, "today", "today's practice problems")
        p.add_argument("--reroll", action="store_true", help="...")
        p.set_defaults(func=run)

    def run(ctx: Ctx) -> int:
        ...
        return 0
"""
from __future__ import annotations

import argparse

# Order here is the order in `dojo --help`.
COMMANDS = [
    "home", "today", "skip", "status", "weak", "upsolve", "retry", "contests",
    "new", "test", "stress", "java",
    "drill", "solve",
    "web", "report", "bar", "sync", "init",
]


def add_command(sub, common: argparse.ArgumentParser, name: str, help: str,
                description: str | None = None, aliases: tuple[str, ...] = ()) -> argparse.ArgumentParser:
    """A subparser that also accepts the global flags (--offline, --refresh, --no-color) after
    the command name, and keeps newlines in its description/epilog."""
    return sub.add_parser(name, help=help, description=description or help, aliases=list(aliases),
                          parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter)
