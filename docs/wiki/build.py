"""Render the wiki user guide: the page templates in docs/wiki/*.md with every `{{run ...}}` line replaced by real, truncated command output.

    .venv/bin/python docs/wiki/build.py OUT_DIR          # writes one .md per template into OUT_DIR (e.g. a clone of the GitHub wiki)

A placeholder is one line:  {{run collection decks --limit 5 | lines=20 | width=150 | skip=3}}
  - the words after `run` are the tool (cards, meta, packages, collection) and its arguments;
  - lines=N keeps the first N lines (default 30), skip=K drops the first K (shown as `...`), header=no leaves out the `$ command` line (for a second excerpt of the same run), width=W cuts long lines (default 160);
  - a truncated block ends with a "... (N more lines)" marker, so a reader knows it goes on.
The samples come from the data in this repository, including the collection file; re-run this after the data or a command changes.
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = Path(__file__).resolve().parent
TOOLS = {"cards": "tools.gundam_cards.cli", "meta": "tools.gundam_meta.cli", "packages": "tools.gundam_packages.cli", "collection": "tools.gundam_collection.cli"}
RUN = re.compile(r"^\{\{run (?P<body>.+?)\}\}\s*$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def sample(body: str) -> str:
    command, *options = (part.strip() for part in body.split("|"))
    opts = dict(o.split("=", 1) for o in options)
    tool, *args = shlex.split(command)
    result = subprocess.run([sys.executable, "-m", TOOLS[tool], *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {command}\n{result.stderr}")
    skip = int(opts.get("skip", 0))
    lines = ANSI.sub("", result.stdout).rstrip("\n").split("\n")[skip:]
    keep, width = int(opts.get("lines", 30)), int(opts.get("width", 160))
    shown = [ln if len(ln) <= width else ln[: width - 1] + "…" for ln in lines[:keep]]
    if len(lines) > keep:
        shown.append(f"... ({len(lines) - keep} more lines)")
    shell = " ".join(shlex.quote(a) for a in args)
    head = [] if opts.get("header") == "no" else [f"$ .venv/bin/python -m {TOOLS[tool]} {shell}"]
    return "\n".join(["```", *head, *(["..."] if skip else []), *shown, "```"])


def render(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        m = RUN.match(line)
        out.append(sample(m["body"]) if m else line)
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, help="directory to write the rendered pages into")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for page in sorted(PAGES.glob("*.md")):
        (args.out / page.name).write_text(render(page.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"wrote {page.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
