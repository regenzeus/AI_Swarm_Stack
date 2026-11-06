#!/usr/bin/env python3
"""The truncation check (AGENTS.md, "Truncation"): no cut is silent and none is unexplained, or the checks fail.

  python3 ops/truncation.py check     every cap without a known reason, every unmarked cut someone reads, every model
                                      answer read without its stop reason; exit 1 when there is one (run by ops/check.sh)
  python3 ops/truncation.py report    every cap with its reason and form, counted per reason and per file

A cap is any of:
  - a slice in Python ([:N], [-N:], [a:N]) or JavaScript (.slice/.substring/.substr) bounded by a literal of 20 or more
    or by an UPPERCASE constant (a limit sized by a name is still a limit);
  - a call of the textcap helpers cut(), tail(), fit(), more(), first() or bounded_json();
  - a CSS text-overflow: ellipsis or line-clamp, or an "ellipsis"/"clamp" class in the app;
  - in a shell script: head -c, cut -c, ${var:a:N}, or head/tail of 2 lines or more;
  - in SQL: a limit of 2 rows or more, or a limit given as a parameter.
Its reason is written on the same line or the line above as `cap: <reason>`:

  prompt     text going to a model (its context budget); the whole text stays where it came from
  untrusted  a bound on what another program, agent, page or model sends (flooding, abuse); never the owner's input
  api        a limit outside our control (Telegram, push, a URL, a mail subject, a file name, a search query)
  id         a title, key, slug or file name made from a text that is kept whole next to it
  parse      a window that code searches or matches; nothing of it is shown
  store      a bound on a stored record, cut visibly (cut/tail) and at least textcap.STORE for what the owner reads
  preview    a short form in the app with a visible marker and one tap to the whole text
  list       a list that shows part of itself and says how many more there are, with a way to see them
  rotate     a rolling window that keeps the newest records on purpose (ids already handled, a price history)

A cut someone reads (prompt, store, preview, untrusted) must show itself: it goes through cut/tail/fit/more/first/
bounded_json, or the line writes its own marker ("…", "more", "earlier", "cut", "in all", "of {len(…)}"). A raw slice
there is a problem even with its reason, because a reader takes the start for the whole (FND-100, FND-103).
A model's answer is read with textcap.answer(), which refuses one that stopped at its output limit; reading
["choices"][0]["message"] directly is a problem.
  top        a short top-N view on purpose (the biggest five, the newest three): nobody's work is left out, and the whole is
             elsewhere. Never for what an owner or an agent asked for: refuse it (textcap.limit_items) or use first().
A list slice of any length needs its reason (FND-123): a loop, a comprehension or a default list cut at [:N]. Other slices
under 20 (short hashes, dates) are not checked; the rules in AGENTS.md still apply to them.
Reads only the repository. Stdlib only.
"""
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REASONS = ("prompt", "untrusted", "api", "id", "parse", "store", "preview", "list", "rotate", "top")
MARKED = {"prompt", "untrusted", "store", "preview"}        # someone reads it: the cut must show itself
MIN = 20
PY = re.compile(r"\[(?:-?\d*:)?-?(\d{2,})\]|\[-(\d{2,}):\]")
PYC = re.compile(r"\[(?:-?\w*:\s*-?[A-Z][A-Z0-9_]{2,}|-[A-Z][A-Z0-9_]{2,}\s*:)\]")
LISTCUT = re.compile(r"\bfor\s+[\w, ()]+\s+in\s+[^:]*\[:\d{1,2}\]\s*:|\bfor\s+.*\bin\b.*\]\[:\d{1,2}\]|\.get\(\s*[\"'][\w-]+[\"']\s*,\s*\[\]\s*\)\[:\d{1,2}\]"
                     r"|\bor \[\]\)\[:\d{1,2}\]|\bsorted\(.*\)\[:\d{1,2}\]")
JS = re.compile(r"\.(?:slice|substring|substr)\(\s*-?\d+\s*,\s*(\d{2,})\s*\)|\.slice\(\s*-(\d{2,})\s*\)")
JSC = re.compile(r"\.(?:slice|substring|substr)\(\s*-?\w+\s*,\s*[A-Z][A-Z0-9_]{2,}\s*\)|\.slice\(\s*-[A-Z][A-Z0-9_]{2,}\s*\)")
CALL = re.compile(r"(?<![\w.])(?:TC\.)?(cut|tail|tailcut|bounded_json)\(|(?<![\w.])TC\.(fit|more|first)\(")
JSCALL = re.compile(r"(?<![\w.])clipped\(")                 # the app's own marked cut (app.js)
NONE = re.compile(r"(?!x)x")
CSS = re.compile(r"text-overflow:\s*ellipsis|line-clamp")
CLS = re.compile(r'class="[^"]*\b(ellipsis|clamp)\b')
SH = re.compile(r"\bhead -c ?\d+|\bcut -c|\$\{\w+:\d+:\d+\}|\b(?:head|tail) -n ?([2-9]|\d{2,})\b|\b(?:head|tail) -([2-9]|\d{2,})\b")
SQL = re.compile(r"\blimit\s+(?:[2-9]|\d{2,}|\?)(?![\w.])", re.I)
SQLCTX = re.compile(r"\b(select|order by|where|from)\b|[\"']\s*\+?\s*$|^\s*[\"']", re.I)
ANSWER = re.compile(r"""\[["']choices["']\]\s*\[0\]\s*\[["']message["']\]""")
OWN = re.compile(r"…|\bmore\b|earlier|\bcut\b(?!\()|in all|of \{len\(")
TAG = re.compile(r"cap:\s*(\w+)")
SKIP = ("ops/textcap.py", "ops/truncation.py")


def files(root=ROOT):
    """The repository's code files; without git (the builder's sandbox copy has no .git) every file under the folders."""
    p = subprocess.run(["git", "ls-files", "ops", "images", "smoke", "config"], cwd=root, capture_output=True, text=True)
    out = p.stdout.split() if p.returncode == 0 else []
    if not out:
        out = [str(f.relative_to(root)) for d in ("ops", "images", "smoke", "config") for f in sorted((Path(root) / d).rglob("*"))
               if f.is_file() and not {"__pycache__", "node_modules"} & set(f.parts)]
    return [f for f in out if f.endswith((".py", ".js", ".css", ".sh")) and "/vendor/" not in f and f not in SKIP
            and not f.endswith("/textcap.py")]


def code_of(f, ln):
    """The line without its comment: a marker or a reason written in a comment is no marker in the text."""
    if f.endswith((".py", ".sh")):
        return re.sub(r"\s#\s.*$|\s#\s*cap:.*$", "", ln)
    if f.endswith(".js"):
        return re.sub(r"/\*.*?\*/|\s//\s.*$", "", ln)
    return ln


def found(f, ln):
    """-> (what the cap is, whether it marks itself) for one line, or None."""
    code = code_of(f, ln)
    what = []
    if f.endswith(".py"):
        what += [m.group(0) for m in PY.finditer(code) if int(m.group(1) or m.group(2)) >= MIN]
        what += [m.group(0) for m in PYC.finditer(code)]
        what += [m.group(0) for m in LISTCUT.finditer(code)]
        what += [m.group(0) for m in SQL.finditer(code) if SQLCTX.search(code)]
    if f.endswith(".js"):
        what += [m.group(0) for m in JS.finditer(ln) if int(m.group(1) or m.group(2)) >= MIN]
        what += [m.group(0) for m in JSC.finditer(ln)] + [m.group(0) for m in CLS.finditer(ln)]
    if f.endswith(".css"):
        what += [m.group(0) for m in CSS.finditer(ln)]
    if f.endswith(".sh"):
        what += [m.group(0) for m in SH.finditer(code)]
    raw = bool(what)
    if not code.lstrip().startswith(("def ", "async def ", "function ")):
        what += [m.group(0) for m in (CALL if f.endswith(".py") else JSCALL if f.endswith(".js") else NONE).finditer(code)]
    if not what:
        return None
    return what[0], not raw or bool(OWN.search(code))


def caps(root=ROOT):
    """-> [(file, line, what, reason or None, marked)] for every cap in the repository."""
    out = []
    for f in files(root):
        lines = (root / f).read_text(errors="replace").splitlines()
        prev_hit = False
        for i, ln in enumerate(lines):
            if ln.lstrip().startswith(("#", "//")) and "cap:" not in ln:
                prev_hit = False
                continue
            hit = found(f, ln)
            if not hit:
                prev_hit = False
                continue
            # the line above lends its reason only when it is no cap itself: one reason never covers two caps
            tag = TAG.search(ln) or (TAG.search(lines[i - 1]) if i and not prev_hit else None)
            out.append((f, i + 1, hit[0], tag.group(1) if tag else None, hit[1]))
            prev_hit = True
    return out


def answers(root=ROOT):
    """-> [(file, line)] where a model's answer is read without textcap.answer()."""
    return [(f, i) for f in files(root) if f.endswith(".py")
            for i, ln in enumerate((root / f).read_text(errors="replace").splitlines(), 1) if ANSWER.search(ln)]


def problems(root=ROOT):
    out = []
    for f, n, what, r, marked in caps(root):
        if r not in REASONS:
            out.append(f"{f}:{n}: {what} has {'no reason' if r is None else f'an unknown reason {r!r}'} "
                       f"(cap: {'|'.join(REASONS)}; AGENTS.md, Truncation)")
        elif r in MARKED and not marked:
            out.append(f"{f}:{n}: {what} cuts what someone reads ({r}) without a mark: use textcap cut/tail/fit/more/first "
                       f"(AGENTS.md, Truncation)")
    out += [f"{f}:{n}: a model's answer read without textcap.answer() (an answer cut at the output limit would pass as whole)"
            for f, n in answers(root)]
    return out


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        bad = problems()
        print("\n".join(bad) or f"   {len(caps())} caps, each with its reason; every cut someone reads is marked")
        return 1 if bad else 0
    if cmd == "report":
        c = caps()
        print(f"{len(c)} caps")
        for (r, m), n in Counter((x[3], "marked" if x[4] else "raw") for x in c).most_common():
            print(f"  {n:4} {r} ({m})")
        for f, n in Counter(x[0] for x in c).most_common():
            print(f"  {n:4} {f}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
