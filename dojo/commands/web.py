"""dojo web — the coach, drills and judge in your browser, served from this machine."""
from __future__ import annotations

import threading
import webbrowser

from dojo.commands import add_command
from dojo.context import Ctx
from dojo.web.server import App, serve

DEFAULT_PORT = 8765


def register(sub, common):
    p = add_command(sub, common, "web", "open dojo in your browser (local server, Ctrl-C stops it)",
                    description="Start a local server on 127.0.0.1 and open dojo in your browser: today's plan, "
                                "upsolve, re-solves, weak tags, contests, drills, the judge and the Java sheet.\n"
                                "Nothing is reachable from other machines. Ctrl-C stops it.")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to listen on (default %(default)s; "
                                                                   "the next free one if taken)")
    p.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    term = ctx.term
    app = App(ctx.cfg, offline=ctx.offline)
    httpd = serve(app, ctx.args.port)
    url = f"http://127.0.0.1:{app.port}/"
    term.out(term.title("dojo web") + "  " + term.link(url, url),
             term.muted("  only this machine can reach it · Ctrl-C stops it"))
    if not ctx.args.no_open:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        term.out(term.muted("\nstopped"))
    finally:
        httpd.server_close()
    return 0
