#!/usr/bin/env python3
"""Claude Code PostToolUse hook for Edit, Write and MultiEdit (DEC-49, docs/CODER-KNOWLEDGE.md): after an edit, the repository's own
linter runs on the changed file and what it finds comes back to the agent at once, so a convention a program can check is kept
while the agent works, not found at review. Builder sandbox only.

The runner names the command in AISTACK_LINT, with {files} where the file goes (ops/repocard.py lint_command: the profile a change
learned, else the repository's own configuration, else the errors that are always errors). Never blocks, never fails a build: a
missing linter, a timeout or any problem prints nothing and exits 0.
"""
import json
import os
import shlex
import subprocess
import sys

TIMEOUT = 20                                         # limit: drops, a linter run past 20 s says nothing (the checks at the end run everything)
LINES = 40                                           # limit: drops, the linter's lines past these are counted (it says how many)
KIND = {"ruff": (".py", ".pyi"), "flake8": (".py",), "black": (".py",), "gofmt": (".go",), "eslint": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")}


def lint(h, command):
    if h.get("hook_event_name") != "PostToolUse" or h.get("tool_name") not in ("Edit", "Write", "MultiEdit") or "{files}" not in command:
        return None
    path = str((h.get("tool_input") or {}).get("file_path") or "")
    cwd = str(h.get("cwd") or os.getcwd())
    if not path:
        return None
    rel = os.path.relpath(path, cwd) if os.path.isabs(path) else path
    if rel.startswith("..") or not os.path.isfile(os.path.join(cwd, rel)):
        return None
    exts = KIND.get(command.split()[0])
    if exts and not rel.endswith(exts):
        return None
    try:
        args = [rel if a == "{files}" else a for a in shlex.split(command)]
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.SubprocessError, OSError, ValueError):     # not there, too slow, or not a command: nothing to say
        return None
    cmd = " ".join(shlex.quote(a) for a in args)
    if p.returncode in (0, 126, 127):                # clean, or the linter is not there
        return None
    out = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
    if not out:
        return None
    more = f"\n(... {len(out) - LINES} more lines)" if len(out) > LINES else ""  # limit: drops, the linter's lines past LINES are counted, not shown (the checks at the end show all)
    return f"The repository's linter on {rel} (`{cmd}`) found this; fix it while you are in the file:\n" + "\n".join(out[:LINES]) + more  # cap: top (LINES)


def main():
    try:
        h = json.load(sys.stdin)
        text = lint(h, os.environ.get("AISTACK_LINT", ""))
    except Exception as e:                           # never on stdout: that is what Claude reads
        print(f"lint hook: {type(e).__name__}: {e}", file=sys.stderr)
        return
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
        notes = os.environ.get("AISTACK_MEMNOTES", "")
        if notes:                                    # beside the build's notes, so the exam and the run page can count what it said
            try:
                with open(notes + ".lint", "a") as f:
                    f.write(json.dumps({"file": str((h.get("tool_input") or {}).get("file_path") or ""), "lines": text.count("\n")}) + "\n")
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"lint hook: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)
