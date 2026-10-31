#!/usr/bin/env python3
"""The truncation check (AGENTS.md, "Truncation"): every place that cuts text names its reason, or the checks fail.

  python3 ops/truncation.py check     every cap without a known reason; exit 1 when there is one (run by ops/check.sh)
  python3 ops/truncation.py report    every cap with its reason, counted per reason and per file

A cap is: a slice with a literal of 40 or more in Python ([:N], [-N:], [a:N]) or JavaScript (.slice/.substring/.substr),
a call of the textcap helpers cut(), tail() or bounded_json(), a CSS text-overflow: ellipsis or line-clamp, or an
"ellipsis"/"clamp" class in the app. Its reason is written on the same line or the line above as `cap: <reason>`:

  prompt     text going to a model (its context budget); the whole text stays where it came from
  untrusted  a bound on what another program, agent, page or model sends (flooding, abuse); never the owner's input
  api        a limit outside our control (Telegram, push, a URL, a mail subject, a file name, a search query)
  id         a title, key, slug or file name made from a text that is kept whole next to it
  parse      a window that code searches or matches; nothing of it is shown
  store      a bound on a stored record, cut visibly (cut/tail) and at least textcap.STORE for what the owner reads
  preview    a short form in the app with a visible marker and one tap to the whole text
  list       a list that shows part of itself and says how many more there are, with a way to see them

Slices under 40 (short hashes, dates, small lists) are not checked here; the rules in AGENTS.md still apply to them.
Reads only the repository. Stdlib only.
"""
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REASONS = ("prompt", "untrusted", "api", "id", "parse", "store", "preview", "list")
PY = re.compile(r"\[(?:-?\d*:)?-?(\d{2,})\]|\[-(\d{2,}):\]")
JS = re.compile(r"\.(?:slice|substring|substr)\(\s*-?\d+\s*,\s*(\d{2,})\s*\)|\.slice\(\s*-(\d{2,})\s*\)")
CALL = re.compile(r"(?<![\w.])(cut|tail|tailcut|bounded_json)\(")
CSS = re.compile(r"text-overflow:\s*ellipsis|line-clamp")
CLS = re.compile(r'class="[^"]*\b(ellipsis|clamp)\b')
TAG = re.compile(r"cap:\s*(\w+)")
SKIP = ("ops/textcap.py", "images/mission-control/textcap.py", "images/swarm/textcap.py", "ops/truncation.py")


def files(root=ROOT):
    """The repository's code files; without git (the builder's sandbox copy has no .git) every file under the folders."""
    p = subprocess.run(["git", "ls-files", "ops", "images", "smoke"], cwd=root, capture_output=True, text=True)
    out = p.stdout.split() if p.returncode == 0 else []
    if not out:
        out = [str(f.relative_to(root)) for d in ("ops", "images", "smoke") for f in sorted((Path(root) / d).rglob("*"))
               if f.is_file() and not {"__pycache__", "node_modules"} & set(f.parts)]
    return [f for f in out if f.endswith((".py", ".js", ".css")) and "/vendor/" not in f and f not in SKIP]


def caps(root=ROOT):
    """-> [(file, line, what, reason or None)] for every cap in the repository."""
    out = []
    for f in files(root):
        lines = (root / f).read_text(errors="replace").splitlines()
        for i, ln in enumerate(lines):
            what = []
            if f.endswith(".py"):
                what += [m.group(0) for m in PY.finditer(ln) if int(m.group(1) or m.group(2)) >= 40]
            if f.endswith(".js"):
                what += [m.group(0) for m in JS.finditer(ln) if int(m.group(1) or m.group(2)) >= 40]
                what += [m.group(0) for m in CLS.finditer(ln)]
            if f.endswith(".css"):
                what += [m.group(0) for m in CSS.finditer(ln)]
            what += [m.group(0) for m in CALL.finditer(ln) if not ln.lstrip().startswith(("def ", "async def "))]
            if not what:
                continue
            tag = TAG.search(ln) or (TAG.search(lines[i - 1]) if i else None)
            out.append((f, i + 1, what[0], tag.group(1) if tag else None))
    return out


def problems(root=ROOT):
    return [f"{f}:{n}: {what} has {'no reason' if r is None else f'an unknown reason {r!r}'} (cap: {'|'.join(REASONS)}; AGENTS.md, Truncation)"
            for f, n, what, r in caps(root) if r not in REASONS]


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        bad = problems()
        print("\n".join(bad) or f"   {len(caps())} caps, each with its reason")
        return 1 if bad else 0
    if cmd == "report":
        c = caps()
        print(f"{len(c)} caps")
        for r, n in Counter(x[3] for x in c).most_common():
            print(f"  {n:4} {r}")
        for f, n in Counter(x[0] for x in c).most_common():
            print(f"  {n:4} {f}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
