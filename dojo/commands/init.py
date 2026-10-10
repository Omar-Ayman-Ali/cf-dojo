"""dojo init — write ~/.config/dojo/config.toml with your defaults, ready to edit."""
from __future__ import annotations

from dojo import paths
from dojo.commands import add_command
from dojo.config import DEFAULT_TOML
from dojo.context import Ctx
from dojo.errors import DojoError


def register(sub, common):
    p = add_command(sub, common, "init", "write the config file (handle, goals, class schedule)")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    path = ctx.args.config or paths.config_path()
    if path.exists() and not ctx.args.force:
        raise DojoError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TOML)
    key, _ = ctx.cfg.api_keys()
    ctx.term.out(f"wrote {path}",
                 ctx.term.muted("API key: " + ("found — group solves will be included" if key
                                               else "not found — only public submissions (see env_file)")))
    return 0
