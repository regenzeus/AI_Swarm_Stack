#!/usr/bin/env python3
"""The Python files kept in parts (PLT-25: server.py and server.chat.py, ...), linted as the one module they run as.

  python3 ops/py_parts_lint.py     exit 1 with each problem as file:line, 0 when clean, 2 when ruff is not installed

A parent runs each part in its own namespace where it stood (_part("server.chat.py")), so a name a part uses may be
defined in the parent and an import in the parent may be used only in a part: linted apart, both look wrong. Each
parent is joined with its parts in place, linted with the same rules as the rest (ops/check.sh), and every problem is
reported at its own file and line. ops/check.sh leaves these files out of its own ruff run.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARENTS = ("images/mission-control/server.py", "ops/missions.py", "ops/builds.py", "images/swarm/ledger.py")
SELECT = "E9,F63,F7,F82,F401,F811"                # the same rules as ops/check.sh's ruff step
PART = re.compile(r'^_part\("([^"]+)"\)')


def joined(parent):
    """The parent with each _part(...) line replaced by that part -> (text, [(file, its first joined line, its line count)])."""
    out, spans, n = [], [], 1
    for i, line in enumerate(parent.read_text().split("\n"), 1):
        m = PART.match(line)
        if not m:
            out.append(line)
            spans.append((parent, n, i))
            n += 1
            continue
        part = parent.with_name(m.group(1))
        for j, pl in enumerate(part.read_text().rstrip("\n").split("\n"), 1):
            out.append(pl)
            spans.append((part, n, j))
            n += 1
    return "\n".join(out) + "\n", spans


def parts_of(parent):
    return [parent.with_name(m.group(1)) for m in (PART.match(x) for x in parent.read_text().split("\n")) if m]


def main():
    ruff = shutil.which("ruff")
    if not ruff:
        print("   ruff is not installed here; the builder and CI images carry it")
        return 2
    bad = []
    with tempfile.TemporaryDirectory() as d:
        for rel in PARENTS:
            parent = ROOT / rel
            text, spans = joined(parent)
            f = Path(d) / parent.name
            f.write_text(text)
            p = subprocess.run([ruff, "check", "--no-cache", "--select", SELECT, "--output-format", "json", str(f)], capture_output=True, text=True)
            for m in json.loads(p.stdout or "[]"):
                src, _, line = spans[m["location"]["row"] - 1]
                bad.append(f"{src.relative_to(ROOT)}:{line}: {m['code']}: {m['message']}")
    for b in bad:
        print("  ", b)
    n = sum(len(parts_of(ROOT / r)) for r in PARENTS)
    print(f"   {len(PARENTS)} files in {len(PARENTS) + n} parts, {len(bad)} problem{'s' if len(bad) != 1 else ''}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
