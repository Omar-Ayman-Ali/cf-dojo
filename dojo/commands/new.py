"""dojo new — create a solution file from your template."""
from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from dojo import paths
from dojo.cf.model import make_key, problem_url
from dojo.commands import add_command
from dojo.context import Ctx
from dojo.errors import DojoError

DESCRIPTION = """\
Create a solution file named like Competitive Programming Helper does (A_Koshary.cpp), with
a header comment linking the problem and your C++ template below it.

  dojo new 2227A
  dojo new 2227 A --java                     CIS 201 practice: A_Koshary.java, class Main
  dojo new https://codeforces.com/gym/104114/problem/B --name "Hello World"

Problem names come from the cached problemset (works offline). Group and gym problems, and
rounds still running, aren't in it: pass --name, or the file is named after the problem id.
--java writes a non-public class Main with a fast reader: it compiles under any file name,
and Codeforces accepts it.
The C++ body is [workspace] template from config.toml if set, else the built-in template."""

URL_RE = re.compile(
    r"codeforces\.[a-z]+/(?:"
    r"(?:contest|gym)/(?P<cid>\d+)/problem/(?P<idx>[A-Za-z]\d?)"
    r"|problemset/(?:gym)?[Pp]roblem/(?P<pcid>\d+)/(?P<pidx>[A-Za-z]\d?)"
    r"|group/(?P<group>[\w-]+)/contest/(?P<gcid>\d+)/problem/(?P<gidx>[A-Za-z]\d?)"
    r")(?![A-Za-z0-9])", re.I)
KEY_RE = re.compile(r"(\d+)\s*[/\-_ ]?\s*([A-Za-z]\d?)")
RUN_RE = re.compile(r"[^\W_]+")


@dataclass
class ProblemRef:
    contest_id: int
    index: str
    url: str | None = None              # as given (without query), when the user passed a URL
    group: str | None = None

    @property
    def key(self) -> str:
        return make_key(self.contest_id, self.index)


def parse_problem(text: str) -> ProblemRef:
    """'2227A', '2227 A', '2227/a', or any Codeforces problem URL (contest, problemset, gym, group)."""
    text = text.strip()
    if "codeforces." in text.lower():
        m = URL_RE.search(text)
        if not m:
            raise DojoError(f"not a Codeforces problem link: {text} — expected …/contest/2227/problem/A")
        g = m.groupdict()
        cid = int(g["cid"] or g["pcid"] or g["gcid"])
        idx = (g["idx"] or g["pidx"] or g["gidx"]).upper()
        return ProblemRef(cid, idx, problem_url(cid, idx, g["group"]), g["group"])
    m = KEY_RE.fullmatch(text)
    if not m:
        raise DojoError(f"not a problem id: {text!r} — use e.g. 2227A, '2227 A' or a problem link")
    return ProblemRef(int(m.group(1)), m.group(2).upper())


def words(text: str) -> list[str]:
    """Like lodash's words(), which CPH uses for file names: split on anything that isn't a
    letter or digit, between letters and digits, and at case changes ('2D' -> 2, D; 'XMLParser'
    -> XML, Parser)."""
    out = []
    for run in RUN_RE.findall(text):
        start = 0
        for i in range(1, len(run)):
            a, b = run[i - 1], run[i]
            nxt = run[i + 1] if i + 1 < len(run) else ""
            if (a.isdigit() != b.isdigit() or (a.islower() and b.isupper())
                    or (a.isupper() and b.isupper() and nxt.islower())):
                out.append(run[start:i])
                start = i
        out.append(run[start:])
    return out


def file_stem(index: str, name: str) -> str:
    """'A', 'Koshary' -> 'A_Koshary'; 'G1', 'Strange Summation' -> 'G_1_Strange_Summation' (as CPH)."""
    return "_".join(words(f"{index}. {name}"))


def builtin_template(name: str) -> str:
    return resources.files("dojo.run").joinpath("templates", name).read_text(encoding="utf-8")


def cpp_template(template: str) -> str:
    if not template:
        return builtin_template("solution.cpp")
    path = Path(template).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise DojoError(f"can't read your template {path} ({e.strerror or e}) — "
                        "fix [workspace] template in config.toml, or set it to \"\" for the built-in one") from None


def render_file(ref: ProblemRef, name: str, url: str, *, java: bool, template: str = "") -> str:
    head = f"// {ref.key} {name} — {url}" if name else f"// {ref.key} — {url}"
    body = builtin_template("Main.java") if java else cpp_template(template)
    return head + "\n" + body + ("" if body.endswith("\n") else "\n")


def register(sub, common):
    p = add_command(sub, common, "new", "create a solution file from your template", description=DESCRIPTION)
    p.add_argument("problem", nargs="+", help="2227A, 2227 A, or a Codeforces problem link")
    p.add_argument("--java", action="store_true", help="write <Index>_<Name>.java (class Main) instead of C++")
    p.add_argument("--dir", metavar="D", help="directory for the file (default: [workspace] dir, ~/cppprimer)")
    p.add_argument("--name", metavar="N", help="problem name, for group/gym problems the cache doesn't know")
    p.add_argument("--open", action="store_true", help="open the file with [workspace] editor")
    p.add_argument("--force", action="store_true", help="overwrite the file if it exists")
    p.set_defaults(func=run)


def run(ctx: Ctx) -> int:
    args, term, cfg = ctx.args, ctx.term, ctx.cfg
    ref = parse_problem(" ".join(args.problem))
    name = (args.name or "").strip()
    url = ref.url
    if not name or not url:
        snap = ctx.snapshot(("problemset", "archive"))
        if not name:
            name = snap.problem(ref.key).name
        url = url or snap.url(ref.key)

    ext = "java" if args.java else "cpp"
    stem = file_stem(ref.index, name) if name else ref.key
    folder = Path(args.dir).expanduser() if args.dir else cfg.workspace_path
    path = folder / f"{stem}.{ext}"
    if path.exists() and not args.force:
        raise DojoError(f"{path} already exists — open it, or pass --force to overwrite")
    text = render_file(ref, name, url, java=args.java, template=cfg.template)
    try:
        paths.ensure(folder)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise DojoError(f"can't write {path}: {e.strerror or e}") from None

    term.out(str(path))
    if not name:
        term.out(term.muted(f'  name unknown, so the file is named {path.name}; --name "…" gives a CPH-style name'))
    elif args.java:
        term.out(term.muted(f"  dojo test {path.name} · submit as Java 21 — the class is Main"))
    else:
        term.out(term.muted(f"  dojo test {path.name} · dojo stress {path.name}"))
    if args.open:
        open_in_editor(cfg.editor, path)
    return 0


def open_in_editor(editor: str, path: Path) -> None:
    argv = shlex.split(editor or "")
    if not argv:
        raise DojoError("no editor set — add editor = \"code\" under [workspace] in config.toml")
    try:
        subprocess.run([*argv, str(path)], check=False)
    except OSError as e:
        raise DojoError(f"can't run your editor {argv[0]!r} ({e.strerror or e}) — "
                        "set [workspace] editor in config.toml") from None
